from pathlib import Path
from datetime import datetime
from PIL import Image, ExifTags
from pillow_heif import register_heif_opener
import pandas as pd

register_heif_opener()

PHOTO_DIR = Path(
    r"G:\My Drive\Le Minh Dang and Thi My Dung Tran - partner visa\Photos and Messages\Photos\Input_Original"
)

SUPPORTED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png",
    ".heic", ".heif", ".webp"
}


def parse_exif_date(value):
    if not value:
        return None

    value = str(value).strip()

    formats = [
        "%Y:%m:%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass

    return None


def get_deep_photo_date(file_path: Path):
    """
    Tìm ngày chụp thật từ:
    1. Nested EXIF IFD -> DateTimeOriginal
    2. Nested EXIF IFD -> DateTimeDigitized
    3. Main EXIF -> DateTimeOriginal
    4. Main EXIF -> DateTimeDigitized
    5. Main EXIF -> DateTime

    Nếu không tìm được:
    - KHÔNG coi file modified time là ngày chụp thật.
    - trả về None để clustering xử lý riêng.
    """

    try:
        with Image.open(file_path) as img:
            exif = img.getexif()

            # ----- Deep/Nested EXIF -----
            try:
                exif_ifd = exif.get_ifd(ExifTags.IFD.Exif)

                for tag, label in [
                    (36867, "EXIF_IFD_DateTimeOriginal"),
                    (36868, "EXIF_IFD_DateTimeDigitized"),
                ]:
                    dt = parse_exif_date(exif_ifd.get(tag))

                    if dt:
                        return dt, label, True

            except Exception:
                pass

            # ----- Main EXIF -----
            for tag, label in [
                (36867, "EXIF_DateTimeOriginal"),
                (36868, "EXIF_DateTimeDigitized"),
                (306, "EXIF_DateTime"),
            ]:
                dt = parse_exif_date(exif.get(tag))

                if dt:
                    return dt, label, True

    except Exception as e:
        return None, f"NO_TRUSTED_DATE ({type(e).__name__})", False

    return None, "NO_TRUSTED_DATE", False


def main():
    print("\nPartner Visa Photo AI - Deep Metadata Scan")
    print("------------------------------------------")
    print(f"Scanning: {PHOTO_DIR}\n")

    if not PHOTO_DIR.exists():
        print("ERROR: Photo folder does not exist.")
        return

    files = [
        p for p in PHOTO_DIR.iterdir()
        if p.is_file()
        and p.suffix.lower() in SUPPORTED_EXTENSIONS
    ]

    print(f"Found {len(files)} supported photos.\n")

    rows = []

    for index, file_path in enumerate(files, start=1):

        captured_at, date_source, trusted = get_deep_photo_date(file_path)

        modified_at = datetime.fromtimestamp(
            file_path.stat().st_mtime
        )

        rows.append({
            "file_name": file_path.name,
            "full_path": str(file_path),
            "extension": file_path.suffix.lower(),
            "captured_at": captured_at,
            "date_source": date_source,
            "trusted_capture_date": trusted,
            "file_modified_at": modified_at,
            "file_size_mb": round(
                file_path.stat().st_size / (1024 * 1024),
                2
            )
        })

        shown_date = captured_at if captured_at else "UNKNOWN"

        print(
            f"[{index}/{len(files)}] "
            f"{shown_date} | {date_source} | {file_path.name}"
        )

    df = pd.DataFrame(rows)

    output_file = Path("photo_metadata_v2.csv")
    df.to_csv(output_file, index=False)

    trusted_count = int(df["trusted_capture_date"].sum())
    unknown_count = len(df) - trusted_count

    print("\n------------------------------------------")
    print("DEEP METADATA SCAN COMPLETE")
    print(f"Photos scanned:       {len(df)}")
    print(f"Trusted capture date: {trusted_count}")
    print(f"Unknown date:         {unknown_count}")
    print(f"Saved to: {output_file.resolve()}")

    unknown = df[df["trusted_capture_date"] == False]

    if not unknown.empty:
        print("\nFILES STILL WITHOUT TRUSTED DATE:")
        print(
            unknown[
                ["file_name", "extension", "file_modified_at"]
            ].to_string(index=False)
        )


if __name__ == "__main__":
    main()