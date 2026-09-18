from pathlib import Path
from datetime import datetime
from PIL import Image
from pillow_heif import register_heif_opener
import pandas as pd

register_heif_opener()

# Google Drive folder chứa ảnh gốc
PHOTO_DIR = Path(
    r"G:\My Drive\Le Minh Dang and Thi My Dung Tran - partner visa\Photos and Messages\Photos\Input_Original"
)

SUPPORTED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".heic",
    ".heif",
    ".webp"
}


def get_photo_date(file_path: Path):
    """
    Ưu tiên lấy ngày chụp từ EXIF.
    Nếu không có EXIF thì dùng file modified time.
    """

    try:
        with Image.open(file_path) as img:
            exif = img.getexif()

            date_tags = [
                (36867, "EXIF_DateTimeOriginal"),
                (36868, "EXIF_DateTimeDigitized"),
                (306, "EXIF_DateTime"),
            ]

            for tag, source in date_tags:
                value = exif.get(tag)

                if value:
                    try:
                        dt = datetime.strptime(
                            str(value),
                            "%Y:%m:%d %H:%M:%S"
                        )
                        return dt, source
                    except ValueError:
                        pass

    except Exception as e:
        return (
            datetime.fromtimestamp(file_path.stat().st_mtime),
            f"file_modified_fallback ({type(e).__name__})"
        )

    return (
        datetime.fromtimestamp(file_path.stat().st_mtime),
        "file_modified_fallback"
    )


def main():
    print("\nPartner Visa Photo AI")
    print("---------------------")
    print(f"Scanning: {PHOTO_DIR}\n")

    if not PHOTO_DIR.exists():
        print("ERROR: Photo folder does not exist.")
        return

    files = [
        p for p in PHOTO_DIR.rglob("*")
        if p.is_file()
        and p.suffix.lower() in SUPPORTED_EXTENSIONS
    ]

    print(f"Found {len(files)} supported photos.")

    rows = []

    for index, file_path in enumerate(files, start=1):

        photo_date, date_source = get_photo_date(file_path)

        rows.append({
            "file_name": file_path.name,
            "full_path": str(file_path),
            "extension": file_path.suffix.lower(),
            "captured_at": photo_date,
            "date_source": date_source,
            "file_size_mb": round(
                file_path.stat().st_size / (1024 * 1024),
                2
            )
        })

        print(
            f"[{index}/{len(files)}] "
            f"{photo_date}  {file_path.name}"
        )

    df = pd.DataFrame(rows)

    if not df.empty:
        df = df.sort_values("captured_at")

    output_file = Path("photo_metadata.csv")
    df.to_csv(output_file, index=False)

    print("\n---------------------")
    print("SCAN COMPLETE")
    print(f"Photos found: {len(df)}")
    print(f"Metadata saved to: {output_file.resolve()}")

    if not df.empty:
        print("\nDate range:")
        print(f"First: {df['captured_at'].min()}")
        print(f"Last:  {df['captured_at'].max()}")


if __name__ == "__main__":
    main()