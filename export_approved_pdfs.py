from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None


# =========================================================
# CONFIG
# =========================================================

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT_DIR = PROJECT_DIR / "APPROVED_WORD"
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "FINAL_PDFS"
TEMP_ROOT = PROJECT_DIR / ".pdf_export_temp"

MAX_PAGES_PER_PDF = 35
TARGET_MB = 4.80
HARD_LIMIT_MB = 5.00

# Only used when a converted PDF part is too large.
# The first strategy that gets the part <= TARGET_MB wins.
# 160 DPI / q78 tested well for photo-evidence pages while keeping text readable.
RASTER_COMPRESSION_STEPS = [
    (160, 78),
    (150, 76),
    (140, 74),
    (130, 72),
    (120, 70),
]


# =========================================================
# CLI / BASIC HELPERS
# =========================================================

def parse_args():
    p = argparse.ArgumentParser(
        description=(
            "Convert lawyer-approved Partner Visa DOCX files to final PDFs. "
            "Each output is capped at 35 pages and targeted below 4.8 MB "
            "(strictly below 5 MB)."
        )
    )
    p.add_argument(
        "--input-dir",
        default=str(DEFAULT_INPUT_DIR),
        help="Folder containing approved DOCX files. Default: APPROVED_WORD",
    )
    p.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Destination folder. Default: FINAL_PDFS",
    )
    p.add_argument(
        "--engine",
        choices=["auto", "word", "libreoffice"],
        default="auto",
        help="DOCX->PDF engine. auto prefers Microsoft Word on Windows, then LibreOffice.",
    )
    p.add_argument(
        "--event",
        default="",
        help="Optional filename/path filter, e.g. --event wedding",
    )
    p.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing matching PDFs.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="List approved DOCX files without exporting.",
    )
    return p.parse_args()


def ensure_dependencies():
    if fitz is None:
        raise RuntimeError("PyMuPDF is required. Install with: pip install pymupdf")


def mb(path: Path) -> float:
    return path.stat().st_size / (1024 * 1024)


def page_count(pdf: Path) -> int:
    with fitz.open(pdf) as doc:
        return doc.page_count


def safe_final_stem(stem: str) -> str:
    stem = re.sub(r"\s+-\s+DRAFT(?:\s*\(\d+\))?$", "", stem, flags=re.I)
    stem = re.sub(r"\s+-\s+APPROVED$", "", stem, flags=re.I)
    stem = re.sub(r"\s+-\s+FINAL$", "", stem, flags=re.I)
    return stem + " - FINAL"


def remove_matching_outputs(folder: Path, final_stem: str):
    if not folder.exists():
        return
    for p in folder.glob(final_stem + "*.pdf"):
        p.unlink(missing_ok=True)


# =========================================================
# DOCX -> PDF CONVERSION
# =========================================================

def find_soffice() -> Path | None:
    candidates = []
    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        candidates.append(Path(found))

    if os.name == "nt":
        candidates.extend([
            Path(r"C:\Program Files\LibreOffice\program\soffice.exe"),
            Path(r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"),
        ])

    for p in candidates:
        if p.exists():
            return p
    return None


def convert_with_word(docx: Path, pdf: Path):
    if os.name != "nt":
        raise RuntimeError("Microsoft Word COM export is Windows-only.")
    try:
        import win32com.client  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "Microsoft Word export needs pywin32. Install with: pip install pywin32"
        ) from e

    pdf.parent.mkdir(parents=True, exist_ok=True)
    word = None
    doc = None
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        doc = word.Documents.Open(str(docx.resolve()), ReadOnly=True)
        # 17 = wdExportFormatPDF
        doc.ExportAsFixedFormat(str(pdf.resolve()), 17)
    finally:
        if doc is not None:
            doc.Close(False)
        if word is not None:
            word.Quit()

    if not pdf.exists() or pdf.stat().st_size == 0:
        raise RuntimeError("Microsoft Word did not create a readable PDF.")


def convert_with_libreoffice(docx: Path, pdf: Path):
    soffice = find_soffice()
    if soffice is None:
        raise RuntimeError("LibreOffice was not found.")

    pdf.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="partner_pdf_lo_") as profile:
        cmd = [
            str(soffice),
            "--headless",
            "--nologo",
            "--nolockcheck",
            f"-env:UserInstallation={Path(profile).resolve().as_uri()}",
            "--convert-to",
            "pdf",
            "--outdir",
            str(pdf.parent),
            str(docx),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

    produced = pdf.parent / (docx.stem + ".pdf")
    if produced.exists() and produced.resolve() != pdf.resolve():
        pdf.unlink(missing_ok=True)
        produced.replace(pdf)

    if not pdf.exists() or pdf.stat().st_size == 0:
        raise RuntimeError(
            "LibreOffice PDF conversion failed.\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )


def convert_docx_to_pdf(docx: Path, pdf: Path, engine: str) -> str:
    errors = []

    if engine in {"auto", "word"}:
        try:
            convert_with_word(docx, pdf)
            return "Microsoft Word"
        except Exception as e:
            errors.append(f"Microsoft Word: {e}")
            if engine == "word":
                raise

    if engine in {"auto", "libreoffice"}:
        try:
            convert_with_libreoffice(docx, pdf)
            return "LibreOffice"
        except Exception as e:
            errors.append(f"LibreOffice: {e}")
            if engine == "libreoffice":
                raise

    raise RuntimeError("No DOCX->PDF engine succeeded:\n- " + "\n- ".join(errors))


# =========================================================
# PDF SPLIT / COMPRESSION / VERIFY
# =========================================================

def split_pdf(source: Path, out_dir: Path, final_stem: str) -> list[Path]:
    """Split to <= MAX_PAGES_PER_PDF. If already within cap, copy as one part."""
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = []

    with fitz.open(source) as src:
        total = src.page_count
        if total <= MAX_PAGES_PER_PDF:
            out = out_dir / f"{final_stem}.pdf"
            shutil.copy2(source, out)
            return [out]

        part_no = 1
        for start in range(0, total, MAX_PAGES_PER_PDF):
            end = min(start + MAX_PAGES_PER_PDF, total)
            part = fitz.open()
            part.insert_pdf(src, from_page=start, to_page=end - 1)
            out = out_dir / f"{final_stem} - Part {part_no}.pdf"
            part.save(out, garbage=4, deflate=True, clean=True)
            part.close()
            outputs.append(out)
            part_no += 1

    return outputs


def raster_flatten_pdf(source: Path, dest: Path, dpi: int, jpeg_quality: int):
    """
    Flatten each PDF page to a JPEG-backed page image.

    This is used ONLY when the normal Word/LibreOffice PDF exceeds the upload-size
    target. It preserves the visual appearance exactly, but the resulting text is
    no longer selectable/searchable. This is acceptable for image-heavy evidence
    PDFs and avoids degrading the approved Word master.
    """
    src = fitz.open(source)
    out = fitz.open()
    zoom = dpi / 72.0

    try:
        for page in src:
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            jpg = pix.tobytes("jpeg", jpg_quality=jpeg_quality)
            new_page = out.new_page(width=page.rect.width, height=page.rect.height)
            new_page.insert_image(new_page.rect, stream=jpg)

        dest.parent.mkdir(parents=True, exist_ok=True)
        out.save(dest, garbage=4, deflate=True, clean=True)
    finally:
        out.close()
        src.close()


def compress_part_if_needed(source_part: Path, work_dir: Path) -> tuple[Path, str]:
    original_size = mb(source_part)
    if original_size <= TARGET_MB:
        return source_part, "original vector PDF"

    print(f"    Oversize part: {original_size:.2f} MB -> compressing")

    best = None
    for dpi, quality in RASTER_COMPRESSION_STEPS:
        candidate = work_dir / f"compressed_{dpi}_{quality}_{source_part.name}"
        raster_flatten_pdf(source_part, candidate, dpi=dpi, jpeg_quality=quality)
        size = mb(candidate)
        print(f"      {dpi} DPI / JPEG q={quality}: {size:.2f} MB")
        best = candidate
        if size <= TARGET_MB:
            return candidate, f"flattened {dpi} DPI / JPEG q={quality}"

    if best is not None and mb(best) < HARD_LIMIT_MB:
        return best, "flattened last-resort hard-limit profile"

    raise RuntimeError(
        f"Could not reduce {source_part.name} below {HARD_LIMIT_MB:.2f} MB. "
        f"Last attempt: {mb(best):.2f} MB" if best else "Compression failed."
    )


def verify_pdf(pdf: Path):
    size = mb(pdf)
    with fitz.open(pdf) as doc:
        pages = doc.page_count
        if pages < 1:
            raise RuntimeError(f"Unreadable PDF: {pdf.name}")
        if pages > MAX_PAGES_PER_PDF:
            raise RuntimeError(f"{pdf.name}: {pages} pages exceeds cap of {MAX_PAGES_PER_PDF}")
        if size >= HARD_LIMIT_MB:
            raise RuntimeError(f"{pdf.name}: {size:.2f} MB is not strictly below 5 MB")

        # Basic render sanity check on first + last page.
        for idx in sorted(set([0, pages - 1])):
            pix = doc.load_page(idx).get_pixmap(matrix=fitz.Matrix(0.5, 0.5), alpha=False)
            if pix.width < 10 or pix.height < 10:
                raise RuntimeError(f"Render verification failed: {pdf.name} page {idx + 1}")


def finalize_part(source: Path, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)
    verify_pdf(dest)


# =========================================================
# EXPORT ONE APPROVED WORD
# =========================================================

def export_one(docx: Path, input_root: Path, output_root: Path, engine: str, overwrite: bool):
    rel_parent = docx.parent.relative_to(input_root) if docx.parent != input_root else Path()
    final_dir = output_root / rel_parent
    final_stem = safe_final_stem(docx.stem)

    existing = sorted(final_dir.glob(final_stem + "*.pdf")) if final_dir.exists() else []
    if existing and not overwrite:
        print(f"  SKIP: final PDF already exists ({existing[0].name})")
        return

    work_dir = TEMP_ROOT / re.sub(r"[^A-Za-z0-9._-]+", "_", docx.stem)[:100]
    shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        converted_pdf = work_dir / "converted.pdf"
        used_engine = convert_docx_to_pdf(docx, converted_pdf, engine)
        print(
            f"  Converted with {used_engine}: "
            f"{page_count(converted_pdf)} pages | {mb(converted_pdf):.2f} MB"
        )

        raw_parts_dir = work_dir / "raw_parts"
        raw_parts = split_pdf(converted_pdf, raw_parts_dir, final_stem)

        final_dir.mkdir(parents=True, exist_ok=True)
        remove_matching_outputs(final_dir, final_stem)

        for idx, raw_part in enumerate(raw_parts, 1):
            compressed, strategy = compress_part_if_needed(raw_part, work_dir)

            if len(raw_parts) == 1:
                final_name = f"{final_stem}.pdf"
            else:
                final_name = f"{final_stem} - Part {idx}.pdf"

            dest = final_dir / final_name
            finalize_part(compressed, dest)
            print(
                f"    SAVED: {dest.name} | {page_count(dest)} pages | "
                f"{mb(dest):.2f} MB | {strategy}"
            )

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# =========================================================
# MAIN
# =========================================================

def main():
    args = parse_args()
    ensure_dependencies()

    input_root = Path(args.input_dir).expanduser().resolve()
    output_root = Path(args.output_dir).expanduser().resolve()

    print("=" * 70)
    print("PARTNER VISA - APPROVED WORD -> FINAL PDF")
    print("=" * 70)
    print(f"Input:          {input_root}")
    print(f"Output:         {output_root}")
    print(f"Max pages:      {MAX_PAGES_PER_PDF} / PDF")
    print(f"Target size:    <= {TARGET_MB:.2f} MB")
    print(f"Hard limit:     <  {HARD_LIMIT_MB:.2f} MB")
    print(f"Engine:         {args.engine}")
    print("Approved Word files are NEVER modified.")
    print()

    if not input_root.exists():
        input_root.mkdir(parents=True, exist_ok=True)
        print(f"Created: {input_root}")
        print("After lawyer approval, copy the approved DOCX files here and run again.")
        return

    docs = sorted(p for p in input_root.rglob("*.docx") if not p.name.startswith("~$"))
    if args.event:
        needle = args.event.lower()
        docs = [p for p in docs if needle in str(p.relative_to(input_root)).lower()]

    if not docs:
        print("No approved DOCX files found.")
        return

    print(f"Approved DOCX files: {len(docs)}")
    for i, docx in enumerate(docs, 1):
        print(f"\n[{i}/{len(docs)}] {docx.relative_to(input_root)}")
        if not args.dry_run:
            export_one(docx, input_root, output_root, args.engine, args.overwrite)

    if args.dry_run:
        print("\nDry run only - nothing exported.")
    else:
        print("\nDONE")
        print(f"Final PDFs: {output_root}")
        print("Open and visually review the final PDFs before submission.")


if __name__ == "__main__":
    main()
