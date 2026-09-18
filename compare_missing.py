from pathlib import Path
from collections import Counter
import re

PHOTOS_DIR = Path(
    r"G:\My Drive\Le Minh Dang and Thi My Dung Tran - partner visa\Photos and Messages\Photos"
)

INPUT_DIR = PHOTOS_DIR / "Input_Original"

MEDIA_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".heic", ".heif",
    ".webp", ".mov", ".mp4", ".m4v"
}


def normalize_name(name: str) -> str:
    """
    So sánh theo tên file, không quan tâm extension và chữ hoa/thường.
    Đồng thời bỏ suffix kiểu '(1)' do Drive thêm khi upload trùng.
    """
    name = name.strip()

    # Bỏ extension nếu có
    stem = Path(name).stem

    # Ví dụ: IMG_1234 (1) -> IMG_1234
    stem = re.sub(r"\s+\(\d+\)$", "", stem)

    return stem.lower().strip()


def main():
    # Tự tìm file manifest dù iPhone có lưu .txt hay không
    manifests = [
        p for p in PHOTOS_DIR.glob("immi_iphone_manifest*")
        if p.is_file()
    ]

    if not manifests:
        print("ERROR: Cannot find immi_iphone_manifest in Photos folder.")
        return

    manifest = manifests[0]

    print(f"iPhone manifest: {manifest}")
    print(f"Drive input:     {INPUT_DIR}\n")

    # Danh sách từ iPhone
    iphone_names = [
        line.strip()
        for line in manifest.read_text(
            encoding="utf-8-sig",
            errors="ignore"
        ).splitlines()
        if line.strip()
    ]

    # Danh sách media trên Drive
    drive_files = [
        p for p in INPUT_DIR.iterdir()
        if p.is_file()
        and p.suffix.lower() in MEDIA_EXTENSIONS
    ]

    iphone_counter = Counter(
        normalize_name(name) for name in iphone_names
    )

    drive_counter = Counter(
        normalize_name(p.name) for p in drive_files
    )

    missing_counter = iphone_counter - drive_counter
    extra_counter = drive_counter - iphone_counter

    missing = []
    for name, count in missing_counter.items():
        missing.extend([name] * count)

    extra = []
    for name, count in extra_counter.items():
        extra.extend([name] * count)

    print("=" * 50)
    print(f"IPHONE ITEMS:        {len(iphone_names)}")
    print(f"DRIVE MEDIA FILES:   {len(drive_files)}")
    print(f"MISSING FROM DRIVE:  {len(missing)}")
    print(f"EXTRA ON DRIVE:      {len(extra)}")
    print("=" * 50)

    print("\nMISSING FROM DRIVE:")
    if missing:
        for name in missing:
            print(name)
    else:
        print("None")

    Path("missing_from_drive.txt").write_text(
        "\n".join(missing),
        encoding="utf-8"
    )

    Path("extra_on_drive.txt").write_text(
        "\n".join(extra),
        encoding="utf-8"
    )

    print("\nReports saved:")
    print(Path("missing_from_drive.txt").resolve())
    print(Path("extra_on_drive.txt").resolve())


if __name__ == "__main__":
    main()