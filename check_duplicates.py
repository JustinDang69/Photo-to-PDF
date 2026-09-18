from pathlib import Path
from collections import defaultdict
import hashlib
import csv

PHOTO_DIR = Path(
    r"G:\My Drive\Le Minh Dang and Thi My Dung Tran - partner visa\Photos and Messages\Photos\Input_Original"
)

SUPPORTED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png",
    ".heic", ".heif", ".webp"
}


def sha256_file(path):
    hasher = hashlib.sha256()

    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)

            if not chunk:
                break

            hasher.update(chunk)

    return hasher.hexdigest()


def main():

    files = [
        p for p in PHOTO_DIR.iterdir()
        if p.is_file()
        and p.suffix.lower() in SUPPORTED_EXTENSIONS
    ]

    print(f"Checking {len(files)} photos for exact duplicates...\n")

    groups = defaultdict(list)

    for index, path in enumerate(files, start=1):

        print(f"[{index}/{len(files)}] {path.name}")

        try:
            file_hash = sha256_file(path)
            groups[file_hash].append(path)
        except Exception as e:
            print(f"ERROR reading {path.name}: {e}")

    duplicates = {
        h: paths
        for h, paths in groups.items()
        if len(paths) > 1
    }

    report = Path("duplicate_report.csv")

    with open(report, "w", newline="", encoding="utf-8-sig") as f:

        writer = csv.writer(f)

        writer.writerow([
            "duplicate_group",
            "sha256",
            "file_name",
            "full_path",
            "size_mb"
        ])

        group_number = 1

        for file_hash, paths in duplicates.items():

            for path in paths:

                writer.writerow([
                    group_number,
                    file_hash,
                    path.name,
                    str(path),
                    round(path.stat().st_size / (1024 * 1024), 2)
                ])

            group_number += 1

    redundant_count = sum(
        len(paths) - 1
        for paths in duplicates.values()
    )

    print("\n------------------------")
    print("DUPLICATE CHECK COMPLETE")
    print(f"Duplicate groups: {len(duplicates)}")
    print(f"Redundant files:  {redundant_count}")
    print(f"Report: {report.resolve()}")

    print("\nIMPORTANT:")
    print("No files were deleted or moved.")


if __name__ == "__main__":
    main()