from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, date
from pathlib import Path
from typing import Iterable

import pandas as pd
from dotenv import load_dotenv
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener
from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt

register_heif_opener()

# =========================================================
# CONFIG
# =========================================================

PROJECT_DIR = Path(__file__).resolve().parent
SELECTION_FILE = PROJECT_DIR / "word_photo_selection.csv"
NOTES_FILE = PROJECT_DIR / "event_notes.csv"
CAPTION_CACHE_FILE = PROJECT_DIR / "word_caption_drafts_v4_2.csv"
BUILD_REPORT_FILE = PROJECT_DIR / "word_build_report_v4_2.csv"
SCENE_PLAN_CACHE_FILE = PROJECT_DIR / "event_scene_plans_v4_2.json"
OUTPUT_DIR = PROJECT_DIR / "WORD_DRAFTS_V4_2"
TEMP_DIR = PROJECT_DIR / ".word_temp_v4_2"

GEMINI_MODEL = "gemini-3.7-flash"
WEDDING_DATE = date(2026, 8, 4)
PARTNER_NAME = "Dung"

API_PREVIEW_MAX_SIDE = 1600
API_PREVIEW_JPEG_QUALITY = 88
WORD_JPEG_QUALITY = 95

MAX_CAPTION_ATTEMPTS = 4
MAX_CAPTION_OUTPUT_TOKENS = 600
GENERAL_MIN_CAPTION_WORDS = 36
SPECIAL_MIN_CAPTION_WORDS = 45
MAX_CAPTION_WORDS = 100

# Quality-first page planning. Portrait/square images are kept large on their own
# page. Two compatible landscape images may share a page vertically.
LANDSCAPE_RATIO = 1.18
MAX_LANDSCAPE_RATIO_SPREAD = 1.28

# Events already agreed should be flagged for category review only.
# The script does NOT change their category automatically.
CATEGORY_REVIEW_FLAGS = {
    "2025-08-15 - Outing with family": (
        "Category review suggested: the note describes opening a joint bank account, "
        "which may fit financial/household evidence better than a social outing."
    ),
    "2025-08-22 - Vehicle registration outing": (
        "Category review suggested: the note describes VicRoads vehicle registration, "
        "which may fit practical/household evidence better than a social outing."
    ),
}

CATEGORY_FOLDER_NAMES = {
    "Social": "01_SOCIAL",
    "Nature of the Household": "02_HOUSEHOLD",
}

# =========================================================
# UTILITIES
# =========================================================


def parse_args():
    parser = argparse.ArgumentParser(
        description="Build Partner Visa photo-evidence Word drafts from selection + notes CSVs."
    )
    parser.add_argument(
        "--no-ai",
        action="store_true",
        help="Do not call Gemini. Use a simple local fallback caption from the verified notes.",
    )
    parser.add_argument(
        "--regenerate-captions",
        action="store_true",
        help="Ignore cached captions and ask Gemini again.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate CSV structure and file paths, then stop before AI/Word generation.",
    )
    parser.add_argument(
        "--event",
        default="",
        help=(
            "Optional test filter. Build only events whose date, name, or event folder "
            "contains this text, e.g. --event 2026-08-04"
        ),
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Skip events whose V4.2 Word draft already exists. This is useful after an "
            "interrupted run and does not call Gemini again for completed events."
        ),
    )
    return parser.parse_args()


def clean_text(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null", "<na>"}:
        return ""
    return text


def is_iso_date_only(text: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", clean_text(text)))


def format_date_long(value: str) -> str:
    dt = datetime.strptime(value, "%Y-%m-%d")
    # Windows does not support %-d, so format manually.
    return f"{dt.day} {dt.strftime('%B %Y')}"


def safe_filename(text: str, max_len: int = 120) -> str:
    text = re.sub(r'[<>:"/\\|?*]', " - ", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text[:max_len].rstrip(" .") or "Untitled Event"


def page_key(event_folder: str, page_number: int, file_names: Iterable[str]) -> str:
    payload = f"{event_folder}|{page_number}|{'|'.join(file_names)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def relationship_rule(event_date: date) -> str:
    if event_date < WEDDING_DATE:
        return (
            "This event happened before the wedding on 4 August 2026. "
            "Refer to Dung as 'Dung', 'my partner, Dung', or use 'Dung and I'. "
            "Do NOT call her 'my wife' or 'my beloved wife' for this event."
        )
    return (
        "This event happened on or after the wedding on 4 August 2026. "
        "You may naturally use 'my wife', 'my beloved wife', 'Dung and I', "
        "or 'as husband and wife'. Do not overuse affectionate wording."
    )


def ensure_inputs_exist():
    missing = [p for p in (SELECTION_FILE, NOTES_FILE) if not p.exists()]
    if missing:
        names = "\n".join(f"  - {p}" for p in missing)
        raise FileNotFoundError(f"Required input file(s) not found:\n{names}")


def load_inputs():
    ensure_inputs_exist()

    selection = pd.read_csv(SELECTION_FILE, keep_default_na=False)
    notes = pd.read_csv(NOTES_FILE, keep_default_na=False)

    required_selection = {
        "category",
        "event_date",
        "event_name",
        "event_folder",
        "file_name",
        "full_path",
        "order",
    }
    required_notes = {"event_folder", "facts", "wording_notes"}

    missing_sel = required_selection - set(selection.columns)
    missing_notes = required_notes - set(notes.columns)

    if missing_sel:
        raise ValueError(f"word_photo_selection.csv is missing columns: {sorted(missing_sel)}")
    if missing_notes:
        raise ValueError(f"event_notes.csv is missing columns: {sorted(missing_notes)}")

    for col in selection.columns:
        if selection[col].dtype == object:
            selection[col] = selection[col].map(clean_text)
    for col in notes.columns:
        if notes[col].dtype == object:
            notes[col] = notes[col].map(clean_text)

    selection["order"] = pd.to_numeric(selection["order"], errors="raise").astype(int)

    if selection.empty:
        raise ValueError("word_photo_selection.csv contains no selected photos.")

    duplicate_rows = selection.duplicated(
        subset=["event_folder", "file_name"], keep=False
    )
    if duplicate_rows.any():
        bad = selection.loc[duplicate_rows, ["event_folder", "file_name"]]
        raise ValueError(
            "Duplicate selected file rows found:\n" + bad.to_string(index=False)
        )

    duplicate_orders = selection.duplicated(
        subset=["event_folder", "order"], keep=False
    )
    if duplicate_orders.any():
        bad = selection.loc[duplicate_orders, ["event_folder", "order", "file_name"]]
        raise ValueError(
            "Duplicate order values found inside an event:\n" + bad.to_string(index=False)
        )

    note_map = notes.set_index("event_folder").to_dict(orient="index")
    missing_note_events = sorted(set(selection["event_folder"]) - set(note_map))
    if missing_note_events:
        raise ValueError(
            "Selected events are missing from event_notes.csv:\n  - "
            + "\n  - ".join(missing_note_events)
        )

    selection = selection.sort_values(
        ["event_date", "event_folder", "order"], kind="stable"
    ).reset_index(drop=True)

    return selection, notes, note_map


def validate_photo_paths(selection: pd.DataFrame):
    missing = []
    for row in selection.itertuples(index=False):
        path = Path(row.full_path)
        if not path.exists():
            missing.append(str(path))

    if missing:
        preview = "\n".join(f"  - {p}" for p in missing[:20])
        suffix = "" if len(missing) <= 20 else f"\n  ... and {len(missing)-20} more"
        raise FileNotFoundError(
            f"{len(missing)} selected photo path(s) are not accessible.\n"
            "Make sure Google Drive for Desktop is mounted and synced.\n"
            f"Examples:\n{preview}{suffix}"
        )


# =========================================================
# IMAGE PREPARATION
# =========================================================


def image_to_jpeg_bytes(path: Path, max_side: int | None, quality: int) -> bytes:
    with Image.open(path) as img:
        img.load()
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")

        if max_side:
            w, h = img.size
            longest = max(w, h)
            if longest > max_side:
                scale = max_side / longest
                img = img.resize(
                    (max(1, round(w * scale)), max(1, round(h * scale))),
                    Image.Resampling.LANCZOS,
                )

        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=quality, optimize=True)
        return buffer.getvalue()


def prepare_word_image(path: Path, temp_dir: Path) -> Path:
    """Create an orientation-normalized high-quality JPEG for reliable DOCX embedding."""
    temp_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:12]
    out = temp_dir / f"{safe_filename(path.stem, 80)}_{digest}.jpg"
    if out.exists():
        return out

    data = image_to_jpeg_bytes(path, max_side=None, quality=WORD_JPEG_QUALITY)
    out.write_bytes(data)
    return out


def image_dimensions(path: Path):
    with Image.open(path) as img:
        img.load()
        img = ImageOps.exif_transpose(img)
        return img.size


# =========================================================
# CAPTION CACHE + GEMINI
# =========================================================

CAPTION_COLUMNS = [
    "page_key",
    "category",
    "event_date",
    "event_name",
    "event_folder",
    "page_number",
    "file_names",
    "caption",
    "model",
]


def load_caption_cache() -> pd.DataFrame:
    if not CAPTION_CACHE_FILE.exists():
        return pd.DataFrame(columns=CAPTION_COLUMNS)

    df = pd.read_csv(CAPTION_CACHE_FILE, keep_default_na=False)
    for col in CAPTION_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[CAPTION_COLUMNS]


def save_caption_cache(df: pd.DataFrame):
    df.to_csv(CAPTION_CACHE_FILE, index=False, encoding="utf-8-sig")


def build_gemini_client():
    load_dotenv(PROJECT_DIR / ".env")
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return None

    try:
        from google import genai
    except ImportError as exc:
        raise RuntimeError(
            "google-genai is not installed. Run: pip install google-genai"
        ) from exc

    return genai.Client(api_key=api_key)


def is_special_event(event_name: str) -> bool:
    text = clean_text(event_name).lower()
    return any(k in text for k in ("wedding", "proposal", "birthday", "engagement", "anniversary"))


def caption_prompt(
    event_date_long: str,
    event_name: str,
    verified_facts: str,
    wording_note: str,
    event_date_obj: date,
    page_number: int,
    page_count: int,
    previous_captions: list[str],
    retry_reason: str = "",
) -> str:
    wording_note = clean_text(wording_note)
    if is_iso_date_only(wording_note):
        # The user wants the full date in every caption. It is already explicitly required.
        wording_note = ""

    special = is_special_event(event_name)
    target = "45-80 words" if special else "36-70 words"

    previous_block = ""
    if previous_captions:
        previous_block = (
            "\nSTYLE MEMORY - captions already used earlier in this event. "
            "Do not repeat their sentence openings or affectionate phrases:\n- "
            + "\n- ".join(previous_captions[-3:])
        )

    optional_wording = (
        f"\nCLIENT WORDING PREFERENCE: {wording_note}" if wording_note else ""
    )
    retry_block = (
        f"\nIMPORTANT RETRY NOTE: The previous attempt was rejected because: {retry_reason}. "
        "Write a completely fresh, complete caption."
        if retry_reason else ""
    )

    return f"""
Write ONE polished photo-evidence caption in first person from Minh's perspective.

EVENT DATE: {event_date_long}
EVENT: {event_name}
VERIFIED CLIENT FACTS: {verified_facts}
PAGE: {page_number} of {page_count}

RELATIONSHIP TIMELINE:
{relationship_rule(event_date_obj)}

WRITING GOAL:
- Write 2-3 complete sentences, approximately {target}.
- The first sentence MUST naturally include the exact full date: {event_date_long}.
- Describe the moment/activity visible in the selected image(s), using the verified facts only when relevant to what is shown on this page.
- Make the wording warm, affectionate and human. For important milestones such as a wedding, proposal or birthday, let the emotional significance come through naturally.
- Use simple English. It should sound like a real partner describing a meaningful memory, not a legal template or AI output.
- If the page has two images, write one cohesive caption for the shared moment/activity.
- If the verified event note contains several activities, mention only the activity relevant to the current image(s), unless the images genuinely connect those activities.

ACCURACY RULES:
- Do not invent people, names, relationships, places, emotions, reasons or activities that are not in the verified facts or clearly visible.
- Do not call Dung 'my wife' before the wedding date.
- Preserve practical verified details when they are relevant, including appointments, errands or household activities.

OUTPUT RULES:
- Return only the finished caption text.
- No heading, no bullet points, no markdown, no quotation marks.
- Never mention these instructions, 'verified facts', AI, visa, evidence, page numbers, prompts, or 'the photo'.
- Never output fragments such as 'arm-in-arm', 'holding arms', 'On 4 August', or instruction text such as 'Avoid repetitive phrases'.
- Every sentence must be grammatically complete.
{optional_wording}{previous_block}{retry_block}
""".strip()


def normalize_caption(text: str) -> str:
    text = clean_text(text)
    text = text.strip('"“”')
    text = re.sub(r"^caption\s*:\s*", "", text, flags=re.IGNORECASE)
    text = text.replace("**", "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def caption_quality_error(caption: str, event_date_long: str, event_name: str) -> str:
    caption = normalize_caption(caption)
    words = re.findall(r"\b[\w'-]+\b", caption)
    min_words = SPECIAL_MIN_CAPTION_WORDS if is_special_event(event_name) else GENERAL_MIN_CAPTION_WORDS

    if not caption:
        return "empty output"
    if event_date_long not in caption:
        return f"the full date '{event_date_long}' is missing"
    if len(words) < min_words:
        return f"too short ({len(words)} words; minimum {min_words})"
    if len(words) > MAX_CAPTION_WORDS:
        return f"too long ({len(words)} words; maximum {MAX_CAPTION_WORDS})"

    lower = caption.lower()
    forbidden = [
        "avoid repetitive phrases", "strict writing rules", "verified facts",
        "relationship timeline", "return only", "prompt", "as an ai",
        "photo evidence", "visa evidence", "attached photo", "this photo",
        "page 1", "page 2", "page 3",
    ]
    for phrase in forbidden:
        if phrase in lower:
            return f"instruction/prompt leakage detected: '{phrase}'"

    # Reject obvious fragments/truncation.
    if caption[-1] not in ".!?":
        return "caption does not end as a complete sentence"
    if re.search(r"\b(and|with|to|at|the|our|my|a|an)\s*[.!?]?$", lower):
        return "caption appears to end in a fragment"
    if len(re.findall(r"[.!?]", caption)) < 2:
        return "caption should contain at least two complete sentences"

    return ""


def generate_caption_with_gemini(
    client,
    page_rows: pd.DataFrame,
    event_date_long: str,
    event_name: str,
    verified_facts: str,
    wording_note: str,
    event_date_obj: date,
    page_number: int,
    page_count: int,
    previous_captions: list[str],
    retry_reason: str = "",
) -> str:
    try:
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError(
            "google-genai is not installed correctly. Run: pip install --upgrade google-genai"
        ) from exc

    contents = [
        caption_prompt(
            event_date_long,
            event_name,
            verified_facts,
            wording_note,
            event_date_obj,
            page_number,
            page_count,
            previous_captions,
            retry_reason=retry_reason,
        )
    ]

    for row in page_rows.itertuples(index=False):
        image_bytes = image_to_jpeg_bytes(
            Path(row.full_path),
            max_side=API_PREVIEW_MAX_SIDE,
            quality=API_PREVIEW_JPEG_QUALITY,
        )
        contents.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))

    schema = {
        "type": "object",
        "properties": {
            "caption": {
                "type": "string",
                "description": "The complete polished caption only."
            }
        },
        "required": ["caption"],
        "additionalProperties": False,
    }

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            max_output_tokens=MAX_CAPTION_OUTPUT_TOKENS,
            thinking_config=types.ThinkingConfig(thinking_level="low"),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            response_mime_type="application/json",
            response_json_schema=schema,
        ),
    )

    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, dict):
        caption = parsed.get("caption", "")
    else:
        raw = clean_text(getattr(response, "text", ""))
        try:
            caption = json.loads(raw).get("caption", "") if raw else ""
        except Exception:
            caption = raw

    caption = normalize_caption(caption)
    if not caption:
        raise RuntimeError("Gemini returned an empty caption.")
    return caption


def local_fallback_caption(event_date_long: str, facts: str, event_date_obj: date) -> str:
    facts = clean_text(facts).rstrip(" .")

    if event_date_obj < WEDDING_DATE:
        facts = re.sub(r"\bmy beloved wife\b", "Dung", facts, flags=re.IGNORECASE)
        facts = re.sub(r"\bmy wife\b", "Dung", facts, flags=re.IGNORECASE)
        facts = re.sub(r"\bI and Dung\b", "Dung and I", facts, flags=re.IGNORECASE)
    else:
        facts = re.sub(r"\bI and my beloved wife\b", "my beloved wife and I", facts, flags=re.IGNORECASE)
        facts = re.sub(r"\bI and my wife\b", "my wife and I", facts, flags=re.IGNORECASE)

    if not facts:
        if event_date_obj < WEDDING_DATE:
            return (
                f"On {event_date_long}, Dung and I spent time together and shared another moment in our life as a couple. "
                "We enjoyed being together and appreciated the simple time we could share."
            )
        return (
            f"On {event_date_long}, my wife and I spent meaningful time together as husband and wife. "
            "We were happy to share the moment and add another special memory to our life together."
        )

    # Remove a duplicated leading date if the note already contains one.
    facts = re.sub(r"^On\s+\d{1,2}\s+[A-Za-z]+\s+\d{4},?\s*", "", facts, flags=re.IGNORECASE)
    first = facts[0].lower() + facts[1:] if facts else facts

    if event_date_obj < WEDDING_DATE:
        closing = "We enjoyed sharing this time together and valued it as another meaningful part of our life as a couple."
    else:
        closing = "We were very happy to share this moment together and treasured it as part of our life as husband and wife."

    return normalize_caption(f"On {event_date_long}, {first}. {closing}")


def get_or_generate_caption(
    cache: pd.DataFrame,
    client,
    use_ai: bool,
    regenerate: bool,
    event_rows: pd.DataFrame,
    page_rows: pd.DataFrame,
    note_row: dict,
    page_number: int,
    page_count: int,
    previous_captions: list[str],
):
    first = event_rows.iloc[0]
    file_names = list(page_rows["file_name"])
    key = page_key(first.event_folder, page_number, file_names)

    existing = cache.loc[cache["page_key"] == key]
    if not regenerate and not existing.empty:
        caption = clean_text(existing.iloc[-1]["caption"])
        if caption:
            return caption, cache, False

    event_date_obj = datetime.strptime(first.event_date, "%Y-%m-%d").date()
    event_date_long = format_date_long(first.event_date)
    facts = clean_text(note_row.get("facts", ""))
    wording_note = clean_text(note_row.get("wording_notes", ""))

    if use_ai and client is not None:
        caption = ""
        retry_reason = ""
        last_exc = None
        for attempt in range(1, MAX_CAPTION_ATTEMPTS + 1):
            try:
                candidate = generate_caption_with_gemini(
                    client=client,
                    page_rows=page_rows,
                    event_date_long=event_date_long,
                    event_name=first.event_name,
                    verified_facts=facts,
                    wording_note=wording_note,
                    event_date_obj=event_date_obj,
                    page_number=page_number,
                    page_count=page_count,
                    previous_captions=previous_captions,
                    retry_reason=retry_reason,
                )
                error = caption_quality_error(candidate, event_date_long, first.event_name)
                if not error:
                    caption = candidate
                    print(f"      Gemini caption quality: OK (attempt {attempt})")
                    break
                retry_reason = error
                print(f"      Gemini caption rejected (attempt {attempt}): {error}")
            except Exception as exc:
                last_exc = exc
                retry_reason = str(exc)
                print(f"      Gemini caption error (attempt {attempt}): {exc}")

        if caption:
            model_name = GEMINI_MODEL
        else:
            reason = retry_reason or (str(last_exc) if last_exc else "unknown error")
            print(f"      WARNING: Gemini could not produce a valid caption after {MAX_CAPTION_ATTEMPTS} attempts: {reason}")
            print("      Using a complete local fact-based fallback for this page.")
            caption = local_fallback_caption(event_date_long, facts, event_date_obj)
            model_name = "local-fallback"
    else:
        caption = local_fallback_caption(event_date_long, facts, event_date_obj)
        model_name = "local-fallback"

    record = {
        "page_key": key,
        "category": first.category,
        "event_date": first.event_date,
        "event_name": first.event_name,
        "event_folder": first.event_folder,
        "page_number": page_number,
        "file_names": " | ".join(file_names),
        "caption": caption,
        "model": model_name,
    }

    cache = cache.loc[cache["page_key"] != key].copy()
    cache = pd.concat([cache, pd.DataFrame([record])], ignore_index=True)
    save_caption_cache(cache)

    return caption, cache, True



# =========================================================
# V4 EVENT-AWARE ROMANTIC CAPTION PLANNING
# =========================================================


def event_plan_key(event_rows: pd.DataFrame, page_plans: list[dict]) -> str:
    first = event_rows.iloc[0]
    payload = [str(first.event_folder)]
    for idx, plan in enumerate(page_plans, start=1):
        payload.append(f"{idx}:{plan['layout']}:{'|'.join(plan['rows']['file_name'].tolist())}")
    return hashlib.sha256("||".join(payload).encode("utf-8")).hexdigest()[:24]


def load_scene_plan_cache() -> dict:
    if not SCENE_PLAN_CACHE_FILE.exists():
        return {}
    try:
        data = json.loads(SCENE_PLAN_CACHE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_scene_plan_cache(cache: dict):
    SCENE_PLAN_CACHE_FILE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def scene_analysis_prompt(
    event_date_long: str,
    event_name: str,
    verified_facts: str,
    event_date_obj: date,
    page_count: int,
) -> str:
    return f"""
You are analysing ALL pages of ONE relationship-photo event before captions are written.

EVENT DATE: {event_date_long}
EVENT: {event_name}
VERIFIED CLIENT FACTS: {verified_facts}
TOTAL PAGES: {page_count}

RELATIONSHIP TIMELINE:
{relationship_rule(event_date_obj)}

TASK:
Study the pages as a sequence, not as unrelated photos. Group consecutive pages that show the same activity or moment into a short scene_group label.

For every page return:
- page_number
- scene_group: short label such as arrival, walking aisle, vows, ring exchange, signing, group photos, dinner
- scene_start: true only on the first page of that scene_group
- visual_summary: concise factual description of what is visible
- new_detail: ONLY the useful detail this page adds beyond earlier pages in the same scene

IMPORTANT:
- Similar consecutive images should normally share the same scene_group.
- Repeated poses or near-identical moments are not new scenes.
- Do not invent identities, relationships, names, places, emotions or actions.
- Use the verified facts only when they help interpret what is visibly happening.
- This stage does NOT write final captions.
""".strip()


def generate_scene_plan_with_gemini(
    client,
    event_rows: pd.DataFrame,
    page_plans: list[dict],
    note_row: dict,
) -> dict:
    try:
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError(
            "google-genai is not installed correctly. Run: pip install --upgrade google-genai"
        ) from exc

    first = event_rows.iloc[0]
    event_date_obj = datetime.strptime(first.event_date, "%Y-%m-%d").date()
    event_date_long = format_date_long(first.event_date)
    facts = clean_text(note_row.get("facts", ""))

    contents = [
        scene_analysis_prompt(
            event_date_long=event_date_long,
            event_name=first.event_name,
            verified_facts=facts,
            event_date_obj=event_date_obj,
            page_count=len(page_plans),
        )
    ]

    # Give Gemini explicit page boundaries, then the image(s) for that page.
    for page_number, plan in enumerate(page_plans, start=1):
        names = ", ".join(plan["rows"]["file_name"].tolist())
        contents.append(f"PAGE {page_number} OF {len(page_plans)} | FILES: {names}")
        for row in plan["rows"].itertuples(index=False):
            image_bytes = image_to_jpeg_bytes(
                Path(row.full_path),
                max_side=1280,
                quality=84,
            )
            contents.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))

    schema = {
        "type": "object",
        "properties": {
            "pages": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "page_number": {"type": "integer"},
                        "scene_group": {"type": "string"},
                        "scene_start": {"type": "boolean"},
                        "visual_summary": {"type": "string"},
                        "new_detail": {"type": "string"},
                    },
                    "required": [
                        "page_number", "scene_group", "scene_start",
                        "visual_summary", "new_detail"
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["pages"],
        "additionalProperties": False,
    }

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            max_output_tokens=1800,
            thinking_config=types.ThinkingConfig(thinking_level="low"),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            response_mime_type="application/json",
            response_json_schema=schema,
        ),
    )

    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, dict):
        result = parsed
    else:
        raw = clean_text(getattr(response, "text", ""))
        result = json.loads(raw) if raw else {}

    pages = result.get("pages", []) if isinstance(result, dict) else []
    if len(pages) != len(page_plans):
        raise RuntimeError(
            f"Scene analysis returned {len(pages)} pages; expected {len(page_plans)}."
        )

    expected = list(range(1, len(page_plans) + 1))
    got = [int(x.get("page_number", -1)) for x in pages]
    if got != expected:
        raise RuntimeError(f"Scene analysis page numbers are invalid: {got}")

    # Normalize scene continuity: the first occurrence of a group is scene_start,
    # and immediately repeated pages in the same group become continuations.
    last_group = None
    for item in pages:
        group = clean_text(item.get("scene_group", "")) or "event moment"
        item["scene_group"] = group
        item["visual_summary"] = clean_text(item.get("visual_summary", ""))
        item["new_detail"] = clean_text(item.get("new_detail", ""))
        item["scene_start"] = (group.lower() != (last_group or "").lower())
        last_group = group

    return {"pages": pages}


def caption_plan_prompt(
    event_date_long: str,
    event_name: str,
    verified_facts: str,
    wording_note: str,
    event_date_obj: date,
    scene_plan: dict,
    retry_reason: str = "",
) -> str:
    wording_note = clean_text(wording_note)
    if is_iso_date_only(wording_note):
        wording_note = ""

    plan_json = json.dumps(scene_plan, ensure_ascii=False, indent=2)
    optional_wording = f"\nCLIENT WORDING PREFERENCE: {wording_note}" if wording_note else ""
    retry_block = (
        f"\nRETRY FEEDBACK FROM QUALITY CHECK: {retry_reason}\n"
        "Correct that problem explicitly while rewriting the WHOLE sequence."
        if retry_reason else ""
    )

    special_style = ""

    if is_special_event(event_name):
        special_style = """
IMPORTANT-MILESTONE VOICE:
- This is an important relationship milestone, so the writing should feel genuinely affectionate and personal.
- Let warmth come through naturally with varied phrases such as "my beloved wife", "we were so happy", "I treasured this moment", "we shared this special moment", or "as husband and wife" when they fit.
- Do NOT use all of those phrases, and do NOT repeat one phrase mechanically.
- The tone should feel like a husband remembering an important day with the woman he loves, while staying simple and believable.
"""

    return f"""
Write the COMPLETE set of captions for ONE relationship event as a coordinated story.
You are writing in FIRST PERSON from Minh's perspective.

EVENT DATE: {event_date_long}
EVENT: {event_name}
VERIFIED CLIENT FACTS: {verified_facts}

RELATIONSHIP TIMELINE:
{relationship_rule(event_date_obj)}

SCENE PLAN:
{plan_json}

CORE GOAL:
The captions must feel like one real memory unfolding across the pages, not 16 separate image descriptions.
Each scene should have its own purpose. Once an event-level fact or visual detail has been established, remember it and move forward.

VOICE:
- Warm, affectionate, sincere and natural.
- Simple English, as if Minh is personally writing about a meaningful memory with Dung.
- Romantic enough to show genuine affection, but never exaggerated, poetic, legalistic or artificial.
- Use "we", "us", "Dung", "my wife", and occasionally "my beloved wife" after the wedding date.
- Prefer relationship language over camera-description language.
- Do not mechanically copy the verified facts. Rewrite them naturally.
{special_style}

EVENT-WIDE REPETITION RULES:
1. Write the exact full date "{event_date_long}" ONLY ONCE in the entire event, in the first caption.
2. Introduce the overall event and who attended only once. The exact phrase "friends and colleagues" may appear at most once.
3. A repeated bouquet, flower backdrop, clothing, venue, smile, or guest group should be described only when it adds something genuinely new.
4. Consecutive pages in the same scene_group are ONE moment. Explain the activity on the scene_start page. Continuation pages should add only a fresh action, expression, interaction or feeling.
5. Do not restart later pages with "During our wedding", "Dung and I", "My wife and I", or the event title over and over.
6. Do not repeat generic endings such as "another meaningful moment", "a special part of our day", "we were happy to share this moment", or close variants on multiple pages.
7. If two pages are near-duplicates, the second caption may be short and intimate rather than inventing a new story.

VERY IMPORTANT - HUMAN, NOT PHOTOGRAPHER LANGUAGE:
- Never write "wide shot", "close-up", "fuller view", "perspective", "frame", "image", "photo", "attendees", "bride", "groom", "couple", or describe architecture/camera composition.
- Describe what WE were doing and what the moment meant to us.

SCENE STORYTELLING EXAMPLE FOR A WEDDING:
- Entrance/walking: introduce the wedding once, then describe walking together only once or twice without repeating the date, bouquet and guests.
- Ceremony/vows: one caption can introduce standing before the celebrant.
- Rings: one caption for Minh placing Dung's ring; one for Dung placing Minh's ring; do not repeat the whole wedding context.
- Signing/portraits: move the story forward to making the marriage official and sharing the occasion with guests.
- Dinner: transition naturally to celebrating together after the ceremony.

CAPTION LENGTH:
- First page: about 38-75 words, usually 2-3 sentences.
- First page of a new scene: about 25-60 words, usually 1-3 sentences.
- Continuation in the same scene: about 14-42 words, usually 1-2 sentences.
- A short continuation is better than repetitive filler.

FACT SAFETY:
- Do not invent names, relationships, places, actions, promises or specific emotions not supported by verified facts or clearly visible context.
- Warm relationship wording is welcome, but keep it believable and grounded.
- Do not mention AI, prompts, visa, evidence, page numbers or these instructions.
- Every caption must be grammatical and complete.

Return exactly one caption for every page in the scene plan, preserving page order.
{optional_wording}
{retry_block}
""".strip()


def generate_event_captions_with_gemini(
    client,
    event_rows: pd.DataFrame,
    note_row: dict,
    scene_plan: dict,
    retry_reason: str = "",
) -> list[dict]:
    try:
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError(
            "google-genai is not installed correctly. Run: pip install --upgrade google-genai"
        ) from exc

    first = event_rows.iloc[0]
    event_date_obj = datetime.strptime(first.event_date, "%Y-%m-%d").date()
    event_date_long = format_date_long(first.event_date)
    facts = clean_text(note_row.get("facts", ""))
    wording_note = clean_text(note_row.get("wording_notes", ""))

    schema = {
        "type": "object",
        "properties": {
            "pages": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "page_number": {"type": "integer"},
                        "caption": {"type": "string"},
                    },
                    "required": ["page_number", "caption"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["pages"],
        "additionalProperties": False,
    }

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[caption_plan_prompt(
            event_date_long=event_date_long,
            event_name=first.event_name,
            verified_facts=facts,
            wording_note=wording_note,
            event_date_obj=event_date_obj,
            scene_plan=scene_plan,
            retry_reason=retry_reason,
        )],
        config=types.GenerateContentConfig(
            max_output_tokens=3600,
            thinking_config=types.ThinkingConfig(thinking_level="medium"),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            response_mime_type="application/json",
            response_json_schema=schema,
        ),
    )

    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, dict):
        result = parsed
    else:
        raw = clean_text(getattr(response, "text", ""))
        result = json.loads(raw) if raw else {}

    pages = result.get("pages", []) if isinstance(result, dict) else []
    return [
        {"page_number": int(x.get("page_number", -1)), "caption": normalize_caption(x.get("caption", ""))}
        for x in pages
    ]


def polish_prompt(
    event_date_long: str,
    event_name: str,
    verified_facts: str,
    event_date_obj: date,
    scene_plan: dict,
    draft_pages: list[dict],
    retry_reason: str = "",
) -> str:
    scene_json = json.dumps(scene_plan, ensure_ascii=False, indent=2)
    draft_json = json.dumps(draft_pages, ensure_ascii=False, indent=2)
    retry_block = (
        f"\nQUALITY FEEDBACK TO FIX: {retry_reason}\n"
        "Rewrite the full set so this issue is completely removed."
        if retry_reason else ""
    )
    return f"""
Act as the FINAL relationship-evidence editor for this event.
Rewrite the full caption set as one warm, romantic, natural story from Minh's first-person perspective.

EVENT DATE: {event_date_long}
EVENT: {event_name}
VERIFIED CLIENT FACTS: {verified_facts}
RELATIONSHIP TIMELINE: {relationship_rule(event_date_obj)}

SCENE PLAN:
{scene_json}

CURRENT DRAFT CAPTIONS:
{draft_json}

WHAT TO IMPROVE:
- Keep every useful factual detail, but make the voice more personal, affectionate and human.
- The reader should feel that Minh is remembering a meaningful day with Dung, not labelling pictures.
- For a wedding or other major milestone, use gentle romantic language where natural: "my beloved wife", "we were so happy", "I treasured...", "we shared...", "as husband and wife". Rotate wording and do not overuse any phrase.
- Preserve the event as a sequence: entrance -> ceremony -> rings -> signing/portraits -> celebration/dinner when that is what the scene plan shows.
- Keep continuation captions shorter. Do not force every page to have a full mini-story.
- A continuation caption may be only 1-2 complete sentences (roughly 10-35 words) when the surrounding pages already establish the context.
- Romantic quality comes from sincerity and continuity, not from padding every page with generic emotional phrases.
- Date only once, in caption 1.
- "friends and colleagues" at most once in the whole event.
- Never use detached photographer terms such as wide shot, close-up, fuller view, perspective, bride, groom, couple, attendees, image or photo.
- Remove repeated generic closings and repeated emotional statements.
- Do not invent facts beyond the verified facts and scene plan.
- Simple English only. No legal or poetic vocabulary.

Return exactly one complete caption for every page, in the same page order.
{retry_block}
""".strip()


def polish_event_captions_with_gemini(
    client,
    event_rows: pd.DataFrame,
    note_row: dict,
    scene_plan: dict,
    draft_pages: list[dict],
    retry_reason: str = "",
) -> list[dict]:
    try:
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError(
            "google-genai is not installed correctly. Run: pip install --upgrade google-genai"
        ) from exc

    first = event_rows.iloc[0]
    event_date_obj = datetime.strptime(first.event_date, "%Y-%m-%d").date()
    event_date_long = format_date_long(first.event_date)
    facts = clean_text(note_row.get("facts", ""))

    schema = {
        "type": "object",
        "properties": {
            "pages": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "page_number": {"type": "integer"},
                        "caption": {"type": "string"},
                    },
                    "required": ["page_number", "caption"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["pages"],
        "additionalProperties": False,
    }

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[polish_prompt(
            event_date_long=event_date_long,
            event_name=first.event_name,
            verified_facts=facts,
            event_date_obj=event_date_obj,
            scene_plan=scene_plan,
            draft_pages=draft_pages,
            retry_reason=retry_reason,
        )],
        config=types.GenerateContentConfig(
            max_output_tokens=3800,
            thinking_config=types.ThinkingConfig(thinking_level="medium"),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            response_mime_type="application/json",
            response_json_schema=schema,
        ),
    )

    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, dict):
        result = parsed
    else:
        raw = clean_text(getattr(response, "text", ""))
        result = json.loads(raw) if raw else {}

    pages = result.get("pages", []) if isinstance(result, dict) else []
    return [
        {"page_number": int(x.get("page_number", -1)), "caption": normalize_caption(x.get("caption", ""))}
        for x in pages
    ]


def event_caption_plan_quality_error(
    caption_pages: list[dict],
    scene_plan: dict,
    event_date_long: str,
    event_name: str = "",
) -> str:
    scene_pages = scene_plan.get("pages", [])
    expected_count = len(scene_pages)
    if len(caption_pages) != expected_count:
        return f"returned {len(caption_pages)} captions; expected {expected_count}"

    expected_numbers = list(range(1, expected_count + 1))
    got_numbers = [int(x.get("page_number", -1)) for x in caption_pages]
    if got_numbers != expected_numbers:
        return f"invalid page numbers: {got_numbers}"

    captions = [normalize_caption(x.get("caption", "")) for x in caption_pages]
    if any(not c for c in captions):
        return "one or more captions are empty"

    # Event-level sanity check: individual continuation captions may be concise,
    # but the whole event should still contain enough narrative substance.
    total_words = sum(len(re.findall(r"\b[\w'-]+\b", c)) for c in captions)
    avg_words = total_words / max(1, len(captions))
    if avg_words < 14:
        return (
            f"event captions are too terse overall "
            f"({avg_words:.1f} words/page average; minimum 14)"
        )

    date_hits = sum(c.count(event_date_long) for c in captions)
    if date_hits != 1:
        return f"full date appears {date_hits} times; it must appear exactly once in the event"
    if event_date_long not in captions[0]:
        return "the full date must appear in the first caption"

    joined_lower = "\n".join(captions).lower()
    forbidden = [
        "avoid repetitive phrases", "strict writing rules", "verified facts",
        "relationship timeline", "return only", "prompt", "as an ai",
        "photo evidence", "visa evidence", "attached photo", "this photo",
        "wide shot", "close-up", "close up", "fuller front view",
        "closer perspective", "perspective of", "seating arrangement",
        "mezzanine architecture", "the bride", "the groom", "the couple",
        "attendees", "shared occasion", "another meaningful part",
    ]
    for phrase in forbidden:
        if phrase in joined_lower:
            return f"detached/generic wording detected: '{phrase}'"

    guest_phrase_hits = sum(
        len(re.findall(r"\bfriends\s+and\s+colleagues\b", c.lower()))
        for c in captions
    )
    if guest_phrase_hits > 1:
        return f"'friends and colleagues' appears {guest_phrase_hits} times; maximum is 1"

    openings = []
    for c in captions:
        words = re.findall(r"[A-Za-z']+", c.lower())
        openings.append(" ".join(words[:4]))
    duplicated_openings = sorted({x for x in openings if x and openings.count(x) > 1})
    if duplicated_openings:
        return f"repeated caption opening(s): {duplicated_openings[:3]}"

    # Catch mechanical repeated endings/phrases across captions.
    normalized_sentences = []
    for c in captions:
        for sent in re.split(r"(?<=[.!?])\s+", c):
            norm = re.sub(r"[^a-z ]", "", sent.lower())
            norm = re.sub(r"\s+", " ", norm).strip()
            if len(norm.split()) >= 5:
                normalized_sentences.append(norm)
    repeats = sorted({x for x in normalized_sentences if normalized_sentences.count(x) > 1})
    if repeats:
        return f"repeated sentence detected: '{repeats[0][:80]}'"

    for idx, (cap, scene) in enumerate(zip(captions, scene_pages), start=1):
        words = re.findall(r"\b[\w'-]+\b", cap)
        # Do not force every continuation page to become a mini-essay.
        # Scene transitions can be concise, especially when the previous caption
        # already establishes the event context. The earlier V4 thresholds
        # conflicted with the prompt instruction to keep continuation captions
        # shorter, causing good 15-18 word captions to be rejected repeatedly.
        if idx == 1:
            min_words, max_words = 28, 82
        elif bool(scene.get("scene_start")):
            min_words, max_words = 12, 68
        else:
            min_words, max_words = 8, 48
        if len(words) < min_words:
            return f"page {idx} is too short ({len(words)} words; minimum {min_words})"
        if len(words) > max_words:
            return f"page {idx} is too long ({len(words)} words; maximum {max_words})"
        if cap[-1] not in ".!?":
            return f"page {idx} does not end as a complete sentence"
        if re.search(r"\b(and|with|to|at|the|our|my|a|an)\s*[.!?]?$", cap.lower()):
            return f"page {idx} appears to end in a fragment"

    if is_special_event(event_name):
        # Keep an emotional-quality guard, but do not demand three exact stock phrases.
        # The previous V4.2 rule rejected good birthday/proposal writing simply because
        # Gemini used different warm wording. One clear relationship/emotion signal
        # across the coordinated event is enough; detached camera-description wording
        # is already rejected above.
        markers = [
            "beloved", "wife", "partner", "husband", "love", "together",
            "happy", "joy", "joyful", "special", "meaningful", "treasured",
            "proud", "grateful", "milestone", "future", "relationship",
            "married life", "new chapter", "commitment",
        ]
        marker_hits = sum(1 for m in markers if m in joined_lower)
        if marker_hits < 1:
            return "important-event captions are emotionally flat; add one clear warm relationship detail"

    return ""


def local_event_caption_plan(
    event_rows: pd.DataFrame,
    note_row: dict,
    scene_plan: dict,
) -> list[str]:
    """Only used when the user explicitly runs --no-ai. Never used as silent AI failure output."""
    first = event_rows.iloc[0]
    event_date_obj = datetime.strptime(first.event_date, "%Y-%m-%d").date()
    event_date_long = format_date_long(first.event_date)
    facts = clean_text(note_row.get("facts", "")).rstrip(" .")
    out = []

    for idx, scene in enumerate(scene_plan.get("pages", []), start=1):
        visual = clean_text(scene.get("new_detail", "")) or clean_text(scene.get("visual_summary", ""))
        if idx == 1:
            base = facts or visual or "shared this important occasion together"
            base = re.sub(r"^my wife and i\s+", "", base, flags=re.IGNORECASE)
            base = re.sub(r"^i and my wife\s+", "", base, flags=re.IGNORECASE)
            if event_date_obj < WEDDING_DATE:
                base = re.sub(r"\bmy beloved wife\b|\bmy wife\b", "Dung", base, flags=re.IGNORECASE)
                cap = f"On {event_date_long}, Dung and I {base[0].lower() + base[1:] if base else base}. We were happy to spend this meaningful time together."
            else:
                cap = f"On {event_date_long}, my beloved wife and I {base[0].lower() + base[1:] if base else base}. We were very happy to share this special moment together as husband and wife."
        else:
            if visual:
                cap = f"{visual.rstrip(' .')}. We treasured this part of the day together."
            else:
                cap = "We continued enjoying this special part of the occasion together."
        out.append(normalize_caption(cap))
    return out


def get_or_generate_event_caption_plan(
    cache: pd.DataFrame,
    scene_cache: dict,
    client,
    use_ai: bool,
    regenerate: bool,
    event_rows: pd.DataFrame,
    page_plans: list[dict],
    note_row: dict,
):
    first = event_rows.iloc[0]
    event_key = event_plan_key(event_rows, page_plans)

    expected_keys = [
        page_key(first.event_folder, i, list(plan["rows"]["file_name"]))
        for i, plan in enumerate(page_plans, start=1)
    ]
    if not regenerate:
        cached = cache.loc[cache["page_key"].isin(expected_keys)].copy()
        if len(cached) == len(expected_keys):
            cached_map = {clean_text(r.page_key): clean_text(r.caption) for r in cached.itertuples(index=False)}
            if all(k in cached_map and cached_map[k] for k in expected_keys):
                return [cached_map[k] for k in expected_keys], cache, scene_cache, False

    if use_ai and client is not None:
        if regenerate or event_key not in scene_cache:
            print("      Event analysis: grouping related pages/scenes...")
            scene_plan = generate_scene_plan_with_gemini(
                client=client,
                event_rows=event_rows,
                page_plans=page_plans,
                note_row=note_row,
            )
            scene_cache[event_key] = scene_plan
            save_scene_plan_cache(scene_cache)
        else:
            scene_plan = scene_cache[event_key]
            print("      Event analysis: cached scene plan")

        first_row = event_rows.iloc[0]
        event_date_long = format_date_long(first_row.event_date)

        # Stage B: create a coordinated draft. Retry WITH the actual quality failure reason.
        draft_pages = None
        last_reason = ""
        for attempt in range(1, MAX_CAPTION_ATTEMPTS + 1):
            try:
                candidate = generate_event_captions_with_gemini(
                    client=client,
                    event_rows=event_rows,
                    note_row=note_row,
                    scene_plan=scene_plan,
                    retry_reason=last_reason,
                )
                error = event_caption_plan_quality_error(
                    candidate, scene_plan, event_date_long, first_row.event_name
                )
                if not error:
                    draft_pages = candidate
                    print(f"      Narrative draft quality: OK (attempt {attempt})")
                    break
                last_reason = error
                print(f"      Narrative draft rejected (attempt {attempt}): {error}")
            except Exception as exc:
                last_reason = str(exc)
                print(f"      Narrative draft error (attempt {attempt}): {exc}")

        if draft_pages is None:
            raise RuntimeError(
                "Gemini could not create a valid coordinated narrative for this event. "
                f"Last quality issue: {last_reason}. No low-quality fallback Word was created."
            )

        # Stage C: always run a final relationship-language polish across the WHOLE event.
        polished_pages = None
        last_reason = ""
        for attempt in range(1, MAX_CAPTION_ATTEMPTS + 1):
            try:
                candidate = polish_event_captions_with_gemini(
                    client=client,
                    event_rows=event_rows,
                    note_row=note_row,
                    scene_plan=scene_plan,
                    draft_pages=draft_pages,
                    retry_reason=last_reason,
                )
                error = event_caption_plan_quality_error(
                    candidate, scene_plan, event_date_long, first_row.event_name
                )
                if not error:
                    polished_pages = candidate
                    print(f"      Romantic final polish: OK (attempt {attempt})")
                    break
                last_reason = error
                print(f"      Romantic polish rejected (attempt {attempt}): {error}")
            except Exception as exc:
                last_reason = str(exc)
                print(f"      Romantic polish error (attempt {attempt}): {exc}")

        if polished_pages is None:
            # The coordinated narrative draft has already passed every quality check.
            # A later polish can occasionally make wording worse or trip an overly
            # narrow style rule. In that case keep the validated Gemini narrative
            # instead of aborting the entire 25-event batch. This is NOT the old
            # low-quality local fallback.
            print(
                "      Romantic polish did not improve the validated draft after "
                f"{MAX_CAPTION_ATTEMPTS} attempts; using the validated narrative draft."
            )
            polished_pages = draft_pages
            model_name = f"{GEMINI_MODEL}-validated-event-draft"
        else:
            model_name = f"{GEMINI_MODEL}-event-draft+romantic-polish"

        captions = [normalize_caption(x["caption"]) for x in polished_pages]
    else:
        scene_plan = {
            "pages": [
                {
                    "page_number": i,
                    "scene_group": f"event moment {i}",
                    "scene_start": True,
                    "visual_summary": "",
                    "new_detail": "",
                }
                for i in range(1, len(page_plans) + 1)
            ]
        }
        captions = local_event_caption_plan(event_rows, note_row, scene_plan)
        model_name = "local-event-fallback-explicit-no-ai"

    new_records = []
    for i, (plan, caption) in enumerate(zip(page_plans, captions), start=1):
        file_names = list(plan["rows"]["file_name"])
        key = page_key(first.event_folder, i, file_names)
        scene = scene_plan["pages"][i - 1] if i - 1 < len(scene_plan.get("pages", [])) else {}
        new_records.append({
            "page_key": key,
            "category": first.category,
            "event_date": first.event_date,
            "event_name": first.event_name,
            "event_folder": first.event_folder,
            "page_number": i,
            "file_names": " | ".join(file_names),
            "caption": caption,
            "model": f"{model_name} | scene={clean_text(scene.get('scene_group', ''))}",
        })

    cache = cache.loc[~cache["page_key"].isin(expected_keys)].copy()
    cache = pd.concat([cache, pd.DataFrame(new_records)], ignore_index=True)
    save_caption_cache(cache)
    return captions, cache, scene_cache, True

# =========================================================
# DOCX LAYOUT
# =========================================================


def set_cell_shading(cell, fill="F2F2F2"):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_margins(cell, top=100, start=120, bottom=100, end=120):
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)

    for m, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{m}"))
        if node is None:
            node = OxmlElement(f"w:{m}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def add_caption_box(doc: Document, caption: str):
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True
    cell = table.cell(0, 0)
    set_cell_shading(cell, "F7F7F7")
    set_cell_margins(cell, top=100, start=140, bottom=100, end=140)
    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.08
    run = p.add_run(caption)
    run.font.name = "Arial"
    run.font.size = Pt(11)


def add_image_centered(paragraph, image_path: Path, max_width_inches: float, max_height_inches: float):
    w_px, h_px = image_dimensions(image_path)
    ratio = w_px / h_px if h_px else 1.0

    width = max_width_inches
    height = width / ratio if ratio else max_height_inches
    if height > max_height_inches:
        height = max_height_inches
        width = height * ratio

    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(3)
    run = paragraph.add_run()
    run.add_picture(str(image_path), width=Inches(width), height=Inches(height))


def add_two_landscape_images_stacked(doc: Document, paths: list[Path], is_first_page: bool):
    # Two landscape images can share a page without becoming tiny. Portrait or mixed
    # orientation images are deliberately kept on separate pages by plan_pages().
    max_h = 4.05 if is_first_page else 4.40
    for idx, path in enumerate(paths):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(2 if idx == 0 else 3)
        add_image_centered(p, path, max_width_inches=7.25, max_height_inches=max_h)


def aspect_ratio_for_path(path: Path) -> float:
    w, h = image_dimensions(path)
    return (w / h) if h else 1.0


def compatible_landscape_pair(path_a: Path, path_b: Path) -> bool:
    r1 = aspect_ratio_for_path(path_a)
    r2 = aspect_ratio_for_path(path_b)
    if r1 < LANDSCAPE_RATIO or r2 < LANDSCAPE_RATIO:
        return False
    spread = max(r1, r2) / max(0.01, min(r1, r2))
    return spread <= MAX_LANDSCAPE_RATIO_SPREAD


def setup_document(event_name: str, event_date_long: str, category: str) -> Document:
    doc = Document()
    section = doc.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(1.05)
    section.bottom_margin = Cm(1.05)
    section.left_margin = Cm(1.10)
    section.right_margin = Cm(1.10)

    styles = doc.styles
    normal = styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(10.5)

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_after = Pt(2)
    r = title.add_run(event_name)
    r.bold = True
    r.font.name = "Arial"
    r.font.size = Pt(15)

    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle.paragraph_format.space_after = Pt(5)
    r = subtitle.add_run(f"{event_date_long}  |  {category}")
    r.font.name = "Arial"
    r.font.size = Pt(9.5)
    r.italic = True

    # Ensure the first photo page starts cleanly below the event header.
    return doc


def add_page_content(
    doc: Document,
    image_paths: list[Path],
    layout: str,
    caption: str,
    is_first_page: bool,
    is_last_page: bool,
):
    if not is_first_page:
        doc.add_page_break()

    if layout == "single":
        p = doc.add_paragraph()
        max_h = 8.55 if is_first_page else 9.25
        add_image_centered(
            p, image_paths[0],
            max_width_inches=7.25,
            max_height_inches=max_h,
        )
    elif layout == "stacked-landscape":
        add_two_landscape_images_stacked(doc, image_paths, is_first_page=is_first_page)
    else:
        raise ValueError(f"Unknown page layout: {layout}")

    # No empty spacer paragraph: keep the image(s) as large as possible.
    add_caption_box(doc, caption)


def save_docx_for_event(
    event_rows: pd.DataFrame,
    captions: list[str],
    prepared_pages: list[dict],
) -> Path:
    first = event_rows.iloc[0]
    event_date_long = format_date_long(first.event_date)
    doc = setup_document(first.event_name, event_date_long, first.category)

    for idx, (page, caption) in enumerate(zip(prepared_pages, captions), start=1):
        add_page_content(
            doc,
            image_paths=page["paths"],
            layout=page["layout"],
            caption=caption,
            is_first_page=(idx == 1),
            is_last_page=(idx == len(prepared_pages)),
        )

    props = doc.core_properties
    props.title = f"{event_date_long} - {first.event_name}"
    props.subject = first.category
    props.author = ""
    props.last_modified_by = ""

    category_folder = CATEGORY_FOLDER_NAMES.get(first.category, "99_OTHER")
    out_dir = OUTPUT_DIR / category_folder
    out_dir.mkdir(parents=True, exist_ok=True)

    out_name = safe_filename(f"{first.event_date} - {first.event_name} - DRAFT.docx")
    out_path = out_dir / out_name
    doc.save(out_path)
    return out_path


def expected_docx_path(event_rows: pd.DataFrame) -> Path:
    first = event_rows.iloc[0]
    category_folder = CATEGORY_FOLDER_NAMES.get(first.category, "99_OTHER")
    out_name = safe_filename(f"{first.event_date} - {first.event_name} - DRAFT.docx")
    return OUTPUT_DIR / category_folder / out_name


# =========================================================
# BUILD
# =========================================================


def plan_pages(event_rows: pd.DataFrame) -> list[dict]:
    rows = event_rows.sort_values("order", kind="stable").reset_index(drop=True)
    pages: list[dict] = []
    i = 0

    while i < len(rows):
        current = rows.iloc[i]
        current_path = Path(current.full_path)

        if i + 1 < len(rows):
            nxt = rows.iloc[i + 1]
            next_path = Path(nxt.full_path)
            if compatible_landscape_pair(current_path, next_path):
                pages.append({
                    "rows": rows.iloc[i:i+2].copy(),
                    "layout": "stacked-landscape",
                })
                i += 2
                continue

        pages.append({
            "rows": rows.iloc[i:i+1].copy(),
            "layout": "single",
        })
        i += 1

    return pages


def build_report_row(event_rows: pd.DataFrame, docx_path: Path | None, flag: str):
    first = event_rows.iloc[0]
    pages = plan_pages(event_rows)
    paired_pages = sum(1 for p in pages if p["layout"] == "stacked-landscape")
    return {
        "category": first.category,
        "event_date": first.event_date,
        "event_name": first.event_name,
        "event_folder": first.event_folder,
        "selected_photos": len(event_rows),
        "pages": len(pages),
        "two_photo_landscape_pages": paired_pages,
        "single_photo_event": "YES" if len(event_rows) == 1 else "",
        "category_review_flag": flag,
        "docx_path": str(docx_path) if docx_path else "",
    }


def main():
    args = parse_args()

    print("Partner Visa Word Draft Builder V4.3 Resume - robust romantic narrative + batch resume")
    print("=" * 60)

    selection, notes, note_map = load_inputs()

    if args.event:
        q = args.event.strip().lower()
        mask = (
            selection["event_date"].astype(str).str.lower().str.contains(q, regex=False)
            | selection["event_name"].astype(str).str.lower().str.contains(q, regex=False)
            | selection["event_folder"].astype(str).str.lower().str.contains(q, regex=False)
        )
        selection = selection.loc[mask].copy()
        if selection.empty:
            raise ValueError(f"No selected event matched --event {args.event!r}")
        print(f"Event filter:     {args.event}")

    event_count = selection["event_folder"].nunique()
    print(f"Selected photos: {len(selection)}")
    print(f"Events:          {event_count}")

    validate_photo_paths(selection)
    print("Photo paths:     OK")

    report_rows = []
    for event_folder, event_rows in selection.groupby("event_folder", sort=False):
        flag = CATEGORY_REVIEW_FLAGS.get(event_folder, "")
        report_rows.append(build_report_row(event_rows, None, flag))

    if args.validate_only:
        pd.DataFrame(report_rows).to_csv(BUILD_REPORT_FILE, index=False, encoding="utf-8-sig")
        print(f"Validation complete. Report: {BUILD_REPORT_FILE}")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    use_ai = not args.no_ai
    client = None
    if use_ai:
        client = build_gemini_client()
        if client is None:
            print("WARNING: GEMINI_API_KEY / GOOGLE_API_KEY was not found in .env.")
            print("         Captions will use the local fact-based fallback.")
            use_ai = False
        else:
            print(f"Caption AI:      {GEMINI_MODEL}")
    else:
        print("Caption AI:      disabled (--no-ai)")

    cache = load_caption_cache()
    scene_cache = load_scene_plan_cache()
    final_report = []

    grouped = list(selection.groupby("event_folder", sort=False))
    for event_idx, (event_folder, event_rows) in enumerate(grouped, start=1):
        event_rows = event_rows.sort_values("order", kind="stable").reset_index(drop=True)
        first = event_rows.iloc[0]
        note_row = note_map[event_folder]
        page_plans = plan_pages(event_rows)

        print()
        print(f"[{event_idx}/{len(grouped)}] {first.event_date} - {first.event_name}")
        print(f"    Photos: {len(event_rows)} | Pages: {len(page_plans)}")

        if args.resume:
            existing_docx = expected_docx_path(event_rows)
            if existing_docx.exists():
                print(f"    Existing Word found: SKIPPED ({existing_docx.name})")
                flag = CATEGORY_REVIEW_FLAGS.get(event_folder, "")
                final_report.append(build_report_row(event_rows, existing_docx, flag))
                continue

        captions, cache, scene_cache, was_generated = get_or_generate_event_caption_plan(
            cache=cache,
            scene_cache=scene_cache,
            client=client,
            use_ai=use_ai,
            regenerate=args.regenerate_captions,
            event_rows=event_rows,
            page_plans=page_plans,
            note_row=note_row,
        )
        print("      Coordinated captions:", "generated" if was_generated else "cached")

        prepared_pages = []
        for page_number, plan in enumerate(page_plans, start=1):
            page_rows = plan["rows"]
            layout = plan["layout"]
            file_names = list(page_rows["file_name"])
            print(f"    Page {page_number}/{len(page_plans)} [{layout}]: {', '.join(file_names)}")
            prepared = []
            for row in page_rows.itertuples(index=False):
                prepared.append(prepare_word_image(Path(row.full_path), TEMP_DIR))
            prepared_pages.append({"paths": prepared, "layout": layout})

        docx_path = save_docx_for_event(event_rows, captions, prepared_pages)
        print(f"    Saved: {docx_path}")

        flag = CATEGORY_REVIEW_FLAGS.get(event_folder, "")
        final_report.append(build_report_row(event_rows, docx_path, flag))

    pd.DataFrame(final_report).to_csv(BUILD_REPORT_FILE, index=False, encoding="utf-8-sig")

    print()
    print("=" * 60)
    print("DONE")
    print(f"Word drafts:     {OUTPUT_DIR}")
    print(f"Caption cache:   {CAPTION_CACHE_FILE}")
    print(f"Scene cache:     {SCENE_PLAN_CACHE_FILE}")
    print(f"Build report:    {BUILD_REPORT_FILE}")
    print()
    print("Important: review the DOCX drafts before creating any PDFs.")


if __name__ == "__main__":
    main()
