import os
import io
import json
import time
from pathlib import Path

import pandas as pd
from PIL import Image
from pillow_heif import register_heif_opener
from dotenv import load_dotenv
from google import genai
from google.genai import types


register_heif_opener()

# =========================================================
# CONFIG
# =========================================================
MODEL_NAME = "gemini-3.7-flash"

EVENT_CLUSTERS_FILE = Path("event_clusters.csv")
OUTPUT_FILE = Path("event_classification.csv")
PROGRESS_FILE = Path("event_classification_progress.csv")

PHOTO_BASE_DIR = Path(
    r"G:\My Drive\Le Minh Dang and Thi My Dung Tran - partner visa\Photos and Messages\Photos\Input_Original"
)

MAX_IMAGES_PER_EVENT = 6

# Resize copies sent to Gemini.
# Original files are never changed.
MAX_IMAGE_SIDE = 1280
JPEG_QUALITY = 80

SLEEP_BETWEEN_EVENTS = 1.0


# =========================================================
# IMAGE HELPERS
# =========================================================
def pick_representative_rows(group, max_images=6):
    """
    Select images spread evenly across the event timeline.
    """
    group = group.sort_values("captured_at").reset_index(drop=True)

    n = len(group)

    if n <= max_images:
        return group.copy()

    indexes = []

    for i in range(max_images):
        idx = round(i * (n - 1) / (max_images - 1))
        if idx not in indexes:
            indexes.append(idx)

    return group.iloc[indexes].copy()


def image_to_jpeg_bytes(path: Path):
    """
    Read HEIC/JPG/PNG/etc., resize a temporary in-memory copy,
    convert to JPEG and return bytes.

    Original image is NEVER modified.
    """

    with Image.open(path) as img:
        img.load()

        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        if img.mode == "L":
            img = img.convert("RGB")

        width, height = img.size
        largest_side = max(width, height)

        if largest_side > MAX_IMAGE_SIDE:
            ratio = MAX_IMAGE_SIDE / largest_side

            new_size = (
                max(1, round(width * ratio)),
                max(1, round(height * ratio))
            )

            img = img.resize(
                new_size,
                Image.Resampling.LANCZOS
            )

        buffer = io.BytesIO()

        img.save(
            buffer,
            format="JPEG",
            quality=JPEG_QUALITY,
            optimize=True
        )

        return buffer.getvalue()


def build_image_parts(representatives):
    parts = []

    readable_names = []

    for _, row in representatives.iterrows():

        path = Path(row["full_path"])

        if not path.exists():
            # fallback in case CSV path changes
            path = PHOTO_BASE_DIR / row["file_name"]

        if not path.exists():
            print(f"      WARNING missing: {row['file_name']}")
            continue

        try:
            image_bytes = image_to_jpeg_bytes(path)

            parts.append(
                types.Part.from_bytes(
                    data=image_bytes,
                    mime_type="image/jpeg"
                )
            )

            readable_names.append(row["file_name"])

        except Exception as e:
            print(
                f"      WARNING cannot read "
                f"{row['file_name']}: {e}"
            )

    return parts, readable_names


# =========================================================
# PROMPT
# =========================================================
def build_prompt(event_id, group, sample_names):

    start = pd.to_datetime(group["captured_at"]).min()
    end = pd.to_datetime(group["captured_at"]).max()

    date_text = start.strftime("%Y-%m-%d")

    return f"""
You are assisting with organisation of relationship evidence photos
for an Australian Partner Visa matter.

This is ONE candidate event containing {len(group)} photos.

EVENT METADATA
event_id: {event_id}
date: {date_text}
start_time: {start}
end_time: {end}
representative_files: {", ".join(sample_names)}

TASK

Classify the EVENT into exactly one primary category:

SOCIAL
Use when the event mainly demonstrates the couple's social relationship,
including:
- wedding or engagement celebrations
- birthdays
- family gatherings
- friends or relatives
- holidays and travel
- restaurants or dining out
- parties and celebrations
- public outings
- cultural or community activities
- the couple being socially recognised together

HOUSEHOLD
Use when the event mainly demonstrates shared domestic life, including:
- cooking at home
- living together
- household routines
- chores or cleaning
- furnishing or setting up a home
- groceries or domestic shopping
- moving house
- caring for pets or children at home
- ordinary daily activities in their shared home

REVIEW
Use when:
- the evidence is ambiguous
- SOCIAL vs HOUSEHOLD cannot be determined reliably
- photos appear unrelated or mixed
- representative images do not provide enough context

IMPORTANT RULES

1. Classify the EVENT, not each image independently.
2. Use all supplied representative images together as context.
3. Be conservative. If uncertain, choose REVIEW.
4. Do not identify or guess people's names.
5. Do not invent an event type not supported by the photos.
6. The event title must be short and suitable as a Windows/Google Drive folder.
7. Do not include slash characters in the folder name.
8. Confidence must be from 0.0 to 1.0.
9. Use the supplied event date for the folder date.
10. If the scene is clearly social but the specific occasion is unknown,
    use a neutral title such as "Family gathering", "Couple outing",
    "Restaurant outing" or "Social gathering".
11. If clearly household but activity is uncertain,
    use a neutral title such as "Time at home together"
    or "Shared home life".

Return JSON only.

Schema:

{{
  "event_id": {event_id},
  "primary_bucket": "SOCIAL",
  "event_name": "Birthday with family",
  "confidence": 0.95,
  "reason": "Short factual explanation",
  "suggested_folder_name": "{date_text} - Birthday with family"
}}
""".strip()


# =========================================================
# RESULT HELPERS
# =========================================================
def normalize_bucket(value):

    value = str(value).strip().upper()

    if value not in {
        "SOCIAL",
        "HOUSEHOLD",
        "REVIEW"
    }:
        return "REVIEW"

    return value


def safe_confidence(value):

    try:
        value = float(value)
    except Exception:
        return 0.0

    return max(0.0, min(1.0, value))


def save_progress(results):

    pd.DataFrame(results).to_csv(
        PROGRESS_FILE,
        index=False
    )


# =========================================================
# MAIN
# =========================================================
def main():

    load_dotenv()

    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        print("ERROR: GEMINI_API_KEY missing from .env")
        return

    if not EVENT_CLUSTERS_FILE.exists():
        print("ERROR: event_clusters.csv not found")
        return

    client = genai.Client(api_key=api_key)

    df = pd.read_csv(EVENT_CLUSTERS_FILE)

    df["captured_at"] = pd.to_datetime(
        df["captured_at"]
    )

    event_ids = sorted(
        df["event_id"].unique()
    )

    results = []

    print()
    print(
        "Partner Visa Photo AI - Gemini Event Classification V2"
    )
    print(
        "------------------------------------------------------"
    )
    print(f"Model: {MODEL_NAME}")
    print(f"Candidate events: {len(event_ids)}")
    print()

    for position, event_id in enumerate(
        event_ids,
        start=1
    ):

        group = df[
            df["event_id"] == event_id
        ].copy()

        representatives = pick_representative_rows(
            group,
            MAX_IMAGES_PER_EVENT
        )

        print(
            f"[{position}/{len(event_ids)}] "
            f"Event {event_id} "
            f"({len(group)} photos)"
        )

        try:

            image_parts, sample_names = (
                build_image_parts(representatives)
            )

            if not image_parts:

                result = {
                    "event_id": event_id,
                    "primary_bucket": "REVIEW",
                    "event_name": "Unreadable event",
                    "confidence": 0.0,
                    "reason":
                        "No representative image could be read.",
                    "suggested_folder_name":
                        f"{group['captured_at'].min().date()} "
                        f"- Review event {event_id}",
                    "photo_count": len(group),
                    "representatives_sent": 0,
                    "sample_files": ""
                }

            else:

                prompt = build_prompt(
                    event_id,
                    group,
                    sample_names
                )

                contents = image_parts + [
                    types.Part.from_text(
                        text=prompt
                    )
                ]

                response = (
                    client.models.generate_content(
                        model=MODEL_NAME,
                        contents=contents,
                        config=types.GenerateContentConfig(
                            response_mime_type=(
                                "application/json"
                            ),
                            thinking_config=(
                                types.ThinkingConfig(
                                    thinking_level="low"
                                )
                            )
                        )
                    )
                )

                raw = response.text or "{}"

                parsed = json.loads(raw)

                bucket = normalize_bucket(
                    parsed.get(
                        "primary_bucket",
                        "REVIEW"
                    )
                )

                confidence = safe_confidence(
                    parsed.get(
                        "confidence",
                        0
                    )
                )

                # Additional safety:
                # low-confidence auto results become REVIEW.
                if confidence < 0.70:
                    bucket = "REVIEW"

                result = {
                    "event_id": event_id,
                    "primary_bucket": bucket,
                    "event_name": parsed.get(
                        "event_name",
                        f"Event {event_id}"
                    ),
                    "confidence": confidence,
                    "reason": parsed.get(
                        "reason",
                        ""
                    ),
                    "suggested_folder_name":
                        parsed.get(
                            "suggested_folder_name",
                            (
                                f"{group['captured_at'].min().date()} "
                                f"- Event {event_id}"
                            )
                        ),
                    "photo_count": len(group),
                    "representatives_sent":
                        len(image_parts),
                    "sample_files":
                        " | ".join(sample_names)
                }

            results.append(result)

            save_progress(results)

            print(
                f"    -> "
                f"{result['primary_bucket']} | "
                f"{result['event_name']} | "
                f"{result['confidence']:.2f}"
            )

        except KeyboardInterrupt:
            print()
            print("Stopped by user.")
            save_progress(results)
            print(
                f"Progress saved to: "
                f"{PROGRESS_FILE.resolve()}"
            )
            return

        except Exception as e:

            print(
                f"    ERROR: "
                f"{type(e).__name__}: {e}"
            )

            result = {
                "event_id": event_id,
                "primary_bucket": "REVIEW",
                "event_name":
                    f"Event {event_id} - API error",
                "confidence": 0.0,
                "reason":
                    f"{type(e).__name__}: {e}",
                "suggested_folder_name":
                    (
                        f"{group['captured_at'].min().date()} "
                        f"- Review event {event_id}"
                    ),
                "photo_count": len(group),
                "representatives_sent": 0,
                "sample_files":
                    " | ".join(
                        representatives[
                            "file_name"
                        ].tolist()
                    )
            }

            results.append(result)
            save_progress(results)

        time.sleep(SLEEP_BETWEEN_EVENTS)

    out = pd.DataFrame(results)

    out.to_csv(
        OUTPUT_FILE,
        index=False
    )

    print()
    print(
        "------------------------------------------------------"
    )
    print("CLASSIFICATION COMPLETE")
    print(
        f"Saved: {OUTPUT_FILE.resolve()}"
    )

    print()
    print("Bucket counts:")

    print(
        out["primary_bucket"]
        .value_counts()
        .to_string()
    )

    print()
    print("Results:")
    print(
        out[
            [
                "event_id",
                "primary_bucket",
                "event_name",
                "confidence",
                "photo_count"
            ]
        ].to_string(index=False)
    )


if __name__ == "__main__":
    main()