from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

MAX_PAGES = 30
MAX_MB = 5.0
PREFERRED_MIN_PAGES = 20
MAX_MONTH_SPAN = 3

CATEGORY_OUTPUT = {
    "HOUSEHOLD": "02_HOUSEHOLD",
    "SOCIAL": "03_SOCIAL",
    "COMMITMENT": "04_COMMITMENT",
}

# Documentary evidence is NEVER copied, moved, compressed, or merged by this module.
DOCUMENTARY_PATTERNS = [
    r"electric(?:ity)?", r"gas bill", r"utility", r"bank statement", r"tax return",
    r"family support", r"money transfer", r"transfer receipt", r"shared expense",
    r"education fee", r"parking fine", r"vehicle receipt", r"invoice", r"receipt",
    r"marriage certificate", r"certificate of marriage", r"notice of intended marriage", r"\bnoim\b",
    r"passport", r"birth certificate", r"divorce", r"police (?:check|certificate)",
    r"immigration", r"government", r"form\s*888", r"statutory declaration", r"stat dec",
    r"whatsapp", r"imessage", r"legal document",
]

# Positive signals are intentionally conservative. Folder category is the primary signal;
# these terms help reject ambiguous PDFs rather than trying to classify every PDF on disk.
PHOTO_EVENT_PATTERNS = {
    "SOCIAL": [
        r"outing", r"restaurant", r"dinner", r"lunch", r"cafe", r"coffee", r"gathering",
        r"birthday", r"celebration", r"festival", r"fair", r"pagoda", r"temple", r"wedding",
        r"family", r"friends?", r"club", r"community", r"market", r"christmas",
    ],
    "HOUSEHOLD": [
        r"cooking", r"meal at home", r"eating", r"grocer", r"household", r"home maintenance",
        r"package", r"deliver", r"caring", r"sharing meals", r"home together", r"shared home",
        r"vehicle registration outing",
    ],
    "COMMITMENT": [
        r"airport", r"departure", r"welcom", r"reunion", r"return", r"care", r"support",
    ],
}

DATE_RE = re.compile(r"(?<!\d)(20\d{2})[-_. ](0?[1-9]|1[0-2])[-_. ](0?[1-9]|[12]\d|3[01])(?!\d)")


@dataclass(frozen=True)
class EvidencePDF:
    path: Path
    category: str
    event_date: date | None
    pages: int
    size_mb: float
    classification: str
    reason: str

    @property
    def name(self) -> str:
        return self.path.name


def ensure_dependencies() -> None:
    if fitz is None:
        raise RuntimeError("PyMuPDF is required. Install with: pip install pymupdf")


def mb(path: Path) -> float:
    return path.stat().st_size / (1024 * 1024)


def page_count(path: Path) -> int:
    with fitz.open(path) as doc:
        return doc.page_count


def normalise(text: str) -> str:
    return re.sub(r"[_\-]+", " ", text.lower())


def detect_event_date(filename: str) -> date | None:
    m = DATE_RE.search(filename)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def detect_category(path: Path) -> str | None:
    # Prefer folder location. This module never assigns FINANCIAL.
    parts = [normalise(p) for p in path.parts]
    joined = " / ".join(parts)
    if "household" in joined:
        return "HOUSEHOLD"
    if "social" in joined:
        return "SOCIAL"
    if "commitment" in joined:
        return "COMMITMENT"
    return None


def matches_any(text: str, patterns: Iterable[str]) -> bool:
    return any(re.search(p, text, flags=re.I) for p in patterns)


def classify_pdf(path: Path, category: str | None) -> tuple[str, str]:
    text = normalise(path.name)
    if matches_any(text, DOCUMENTARY_PATTERNS):
        return "DOCUMENTARY_EVIDENCE", "Documentary-evidence filename pattern; left completely untouched."
    if category not in CATEGORY_OUTPUT:
        return "MANUAL_REVIEW", "Eligible photo-evidence category could not be determined from folder location."
    if matches_any(text, PHOTO_EVENT_PATTERNS[category]):
        return "PHOTO_EVENT_EVIDENCE", f"Photo-event filename signal within {category.title()} category."
    # FINAL PDFs in a recognised photo category are plausible, but ambiguity must not auto-process.
    return "MANUAL_REVIEW", "Recognised category but filename does not clearly identify a photo event."


def scan_existing_pdfs(case_root: Path) -> list[EvidencePDF]:
    rows: list[EvidencePDF] = []
    for path in sorted(case_root.rglob("*.pdf")):
        # Never recursively scan our own generated output.
        if "LODGE_READY_MERGE" in path.parts:
            continue
        category = detect_category(path)
        classification, reason = classify_pdf(path, category)
        # Documentary files are intentionally not opened/read further.
        if classification == "DOCUMENTARY_EVIDENCE":
            continue
        try:
            pages = page_count(path)
            size = mb(path)
        except Exception as exc:
            rows.append(EvidencePDF(path, category or "UNKNOWN", detect_event_date(path.name), 0, 0.0,
                                    "MANUAL_REVIEW", f"Could not inspect PDF safely: {exc}"))
            continue
        rows.append(EvidencePDF(path, category or "UNKNOWN", detect_event_date(path.name), pages, size,
                                classification, reason))
    return rows


def month_index(d: date) -> int:
    return d.year * 12 + d.month


def months_covered(items: list[EvidencePDF]) -> int:
    dates = [x.event_date for x in items if x.event_date]
    if not dates:
        return 0
    return month_index(max(dates)) - month_index(min(dates)) + 1


def readable_range(items: list[EvidencePDF]) -> tuple[str, str, str]:
    dates = [x.event_date for x in items if x.event_date]
    if not dates:
        return "", "", ""
    lo, hi = min(dates), max(dates)
    return lo.isoformat(), hi.isoformat(), f"{months_covered(items)} month(s)"


def output_filename(category: str, items: list[EvidencePDF]) -> str:
    dates = [x.event_date for x in items if x.event_date]
    label = category.title()
    if not dates:
        return f"{label} Evidence - Manual Review.pdf"
    lo, hi = min(dates), max(dates)
    if lo.year == hi.year and lo.month == hi.month:
        span = lo.strftime("%b %Y")
    elif lo.year == hi.year:
        span = f"{lo.strftime('%b')} to {hi.strftime('%b %Y')}"
    else:
        span = f"{lo.strftime('%b %Y')} to {hi.strftime('%b %Y')}"
    return f"{label} Evidence - {span}.pdf"


def build_groups(items: list[EvidencePDF]) -> list[dict]:
    """Conservative chronological grouping. This proposes only; it never merges."""
    result: list[dict] = []
    eligible = [x for x in items if x.classification == "PHOTO_EVENT_EVIDENCE"]
    manual = [x for x in items if x.classification != "PHOTO_EVENT_EVIDENCE"]

    # Missing dates can never be auto-grouped.
    dated = sorted([x for x in eligible if x.event_date], key=lambda x: (x.event_date, x.name.lower()))
    undated = [x for x in eligible if not x.event_date]

    i = 0
    while i < len(dated):
        group = [dated[i]]
        j = i + 1
        while j < len(dated):
            candidate = group + [dated[j]]
            if months_covered(candidate) > MAX_MONTH_SPAN:
                break
            if sum(x.pages for x in candidate) > MAX_PAGES:
                break
            # Do not force page count. Adjacent chronological photo events may be proposed.
            group = candidate
            j += 1
        if len(group) >= 2:
            action = "MERGE"
            reason = "Chronological photo-event bundle within 1–3 adjacent months and <=30 pages."
        else:
            action = "KEEP STANDALONE"
            reason = "No suitable adjacent photo event can be added within the current safety limits."
        result.append(plan_row(group[0].category, group, action, reason))
        i += len(group)

    for x in undated:
        result.append(plan_row(x.category, [x], "MANUAL REVIEW", "Event date could not be detected from filename."))
    for x in manual:
        result.append(plan_row(x.category, [x], "MANUAL REVIEW", x.reason))
    return result


def plan_row(category: str, items: list[EvidencePDF], action: str, reason: str) -> dict:
    earliest, latest, months = readable_range(items)
    pages = sum(x.pages for x in items)
    size = sum(x.size_mb for x in items)
    warnings = []
    if pages > MAX_PAGES:
        warnings.append(f"Estimated pages exceed {MAX_PAGES}")
    if size >= MAX_MB:
        warnings.append("Combined source size >=5 MB; merged copy would require optimisation or a smaller group")
    if any(x.event_date is None for x in items):
        warnings.append("Missing event date")
    src = [x.name for x in items]
    return {
        "Category": category,
        "Proposed Output Filename": output_filename(category, items) if action == "MERGE" else src[0],
        "Source PDF 1": src[0] if len(src) > 0 else "",
        "Source PDF 2": src[1] if len(src) > 1 else "",
        "Source PDF 3": src[2] if len(src) > 2 else "",
        "Additional Source PDFs": " | ".join(src[3:]),
        "Earliest Event Date": earliest,
        "Latest Event Date": latest,
        "Months Covered": months,
        "Number of Source PDFs": len(items),
        "Estimated Total Pages": pages,
        "Estimated Combined Size": f"{size:.2f} MB",
        "Proposed Action": action,
        "Reason": reason,
        "Warning": "; ".join(warnings),
    }


PLAN_FIELDS = [
    "Category", "Proposed Output Filename", "Source PDF 1", "Source PDF 2", "Source PDF 3",
    "Additional Source PDFs", "Earliest Event Date", "Latest Event Date", "Months Covered",
    "Number of Source PDFs", "Estimated Total Pages", "Estimated Combined Size", "Proposed Action",
    "Reason", "Warning",
]


def write_category_plans(rows: list[dict], output_root: Path) -> list[Path]:
    written = []
    for category in ("HOUSEHOLD", "SOCIAL", "COMMITMENT"):
        cat_rows = [r for r in rows if r["Category"] == category]
        if not cat_rows:
            continue
        summary = output_root / CATEGORY_OUTPUT[category] / "SUMMARY"
        summary.mkdir(parents=True, exist_ok=True)
        path = summary / f"{category.title()}_Merge_Plan.csv"
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=PLAN_FIELDS)
            writer.writeheader()
            writer.writerows(cat_rows)
        written.append(path)
    return written


def write_scan_report(items: list[EvidencePDF], output_root: Path) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / "SCAN_REPORT.csv"
    fields = ["Category", "Event Date", "Existing PDF", "Pages", "Size MB", "Classification", "Reason", "Source Path"]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for x in items:
            w.writerow({
                "Category": x.category,
                "Event Date": x.event_date.isoformat() if x.event_date else "",
                "Existing PDF": x.name,
                "Pages": x.pages,
                "Size MB": f"{x.size_mb:.2f}",
                "Classification": x.classification,
                "Reason": x.reason,
                "Source Path": str(x.path),
            })
    return path


def parse_args():
    p = argparse.ArgumentParser(description="Prepare Partner Visa photo-event PDF merge PLAN only. No merging is performed.")
    p.add_argument("--case-root", required=True, help="Existing Partner Visa case folder containing completed PDFs.")
    p.add_argument("--output-root", default="", help="New output root. Default: <case-root>/LODGE_READY_MERGE")
    return p.parse_args()


def main():
    ensure_dependencies()
    args = parse_args()
    case_root = Path(args.case_root).expanduser().resolve()
    if not case_root.exists():
        raise SystemExit(f"Case folder not found: {case_root}")
    output_root = Path(args.output_root).expanduser().resolve() if args.output_root else case_root / "LODGE_READY_MERGE"

    print("=" * 72)
    print("PARTNER VISA - PREPARE PDFs FOR LODGEMENT (SCAN + PLAN ONLY)")
    print("=" * 72)
    print(f"Case:             {case_root}")
    print(f"Output:           {output_root}")
    print(f"Max merged pages: {MAX_PAGES}")
    print(f"Max merged size:  < {MAX_MB:.2f} MB")
    print("Preserve originals: ALWAYS ON")
    print("Execution: DISABLED in this preview module")
    print()

    items = scan_existing_pdfs(case_root)
    scan_report = write_scan_report(items, output_root)
    rows: list[dict] = []
    for category in ("HOUSEHOLD", "SOCIAL", "COMMITMENT"):
        cat = [x for x in items if x.category == category]
        if cat:
            rows.extend(build_groups(cat))
    plans = write_category_plans(rows, output_root)

    print(f"Scanned non-documentary/ambiguous PDFs: {len(items)}")
    print(f"Scan report: {scan_report}")
    for p in plans:
        print(f"Merge plan:  {p}")
    print("\nSTOPPED BEFORE MERGING AS REQUIRED.")
    print("Review/edit the category Merge_Plan.csv files before any execution stage is added or run.")


if __name__ == "__main__":
    main()
