from pathlib import Path
import re
import shutil
import pandas as pd


PHOTO_DIR = Path(
    r"G:\My Drive\Le Minh Dang and Thi My Dung Tran - partner visa\Photos and Messages\Photos\Input_Original"
)

OUTPUT_DIR = PHOTO_DIR.parent / "AI_OUTPUT_PREVIEW"

EVENT_CLUSTERS = Path("event_clusters.csv")
CLASSIFICATION = Path("event_classification.csv")
UNKNOWN_PHOTOS = Path("unknown_date_photos.csv")
DUPLICATE_REPORT = Path("duplicate_report.csv")


def safe_folder_name(name):
    name = str(name)

    # Windows-invalid characters
    name = re.sub(r'[<>:"/\\|?*]', "-", name)

    # remove repeated spaces
    name = re.sub(r"\s+", " ", name).strip()

    return name[:120]


def copy_photo(source, destination_folder):
    destination_folder.mkdir(
        parents=True,
        exist_ok=True
    )

    destination = destination_folder / source.name

    # Never overwrite silently
    if destination.exists():
        stem = destination.stem
        suffix = destination.suffix
        counter = 2

        while destination.exists():
            destination = (
                destination_folder /
                f"{stem}__copy{counter}{suffix}"
            )
            counter += 1

    shutil.copy2(source, destination)

    return destination


def main():

    print("\nPartner Visa Photo AI - Build Output")
    print("=" * 55)

    clusters = pd.read_csv(EVENT_CLUSTERS)
    classes = pd.read_csv(CLASSIFICATION)
    unknown = pd.read_csv(UNKNOWN_PHOTOS)

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    social_root = OUTPUT_DIR / "01_SOCIAL"
    household_root = OUTPUT_DIR / "02_HOUSEHOLD"
    review_root = OUTPUT_DIR / "99_REVIEW"

    copied = []
    file_destination_map = {}

    # ========================================
    # 1. COPY TRUSTED-DATE EVENT PHOTOS
    # ========================================

    for _, classification in classes.iterrows():

        event_id = int(classification["event_id"])

        bucket = str(
            classification["primary_bucket"]
        ).upper()

        folder_name = safe_folder_name(
            classification["suggested_folder_name"]
        )

        if bucket == "SOCIAL":
            destination_folder = (
                social_root / folder_name
            )

        elif bucket == "HOUSEHOLD":
            destination_folder = (
                household_root / folder_name
            )

        else:
            destination_folder = (
                review_root /
                safe_folder_name(
                    f"Event {event_id} - "
                    f"{classification['event_name']}"
                )
            )

        event_photos = clusters[
            clusters["event_id"] == event_id
        ]

        print(
            f"Event {event_id:02d} → "
            f"{bucket:<9} → "
            f"{destination_folder.name} "
            f"({len(event_photos)} photos)"
        )

        for _, photo in event_photos.iterrows():

            source = Path(photo["full_path"])

            if not source.exists():
                source = PHOTO_DIR / photo["file_name"]

            if not source.exists():
                print(
                    f"  WARNING missing: "
                    f"{photo['file_name']}"
                )
                continue

            destination = copy_photo(
                source,
                destination_folder
            )

            file_destination_map[
                photo["file_name"]
            ] = destination_folder

            copied.append({
                "file_name": photo["file_name"],
                "source": str(source),
                "destination": str(destination),
                "bucket": bucket,
                "event_id": event_id
            })

    # ========================================
    # 2. UNKNOWN-DATE PHOTOS → REVIEW
    # ========================================

    unknown_folder = (
        review_root / "Unknown Date - Manual Review"
    )

    print(
        f"\nUnknown-date photos → REVIEW "
        f"({len(unknown)} photos)"
    )

    for _, photo in unknown.iterrows():

        source = PHOTO_DIR / photo["file_name"]

        if not source.exists():
            print(
                f"  WARNING missing unknown: "
                f"{photo['file_name']}"
            )
            continue

        destination = copy_photo(
            source,
            unknown_folder
        )

        file_destination_map[
            photo["file_name"]
        ] = unknown_folder

        copied.append({
            "file_name": photo["file_name"],
            "source": str(source),
            "destination": str(destination),
            "bucket": "REVIEW_UNKNOWN_DATE",
            "event_id": ""
        })

    # ========================================
    # 3. COPY EXACT DUPLICATES
    #    into same folder as their keeper
    # ========================================

    if DUPLICATE_REPORT.exists():

        duplicates = pd.read_csv(
            DUPLICATE_REPORT
        )

        print("\nProcessing exact duplicates...")

        for group_id, group in duplicates.groupby(
            "duplicate_group"
        ):

            names = group["file_name"].tolist()

            # Same keeper rule used during clustering
            sorted_names = sorted(
                names,
                key=lambda x: (
                    "(1)" in x,
                    len(x),
                    x.lower()
                )
            )

            keeper = sorted_names[0]

            destination_folder = (
                file_destination_map.get(keeper)
            )

            if destination_folder is None:

                # Safety fallback
                destination_folder = (
                    review_root /
                    "Duplicates - Manual Review"
                )

            for duplicate_name in sorted_names[1:]:

                source = PHOTO_DIR / duplicate_name

                if not source.exists():
                    print(
                        f"  WARNING duplicate missing: "
                        f"{duplicate_name}"
                    )
                    continue

                destination = copy_photo(
                    source,
                    destination_folder
                )

                copied.append({
                    "file_name": duplicate_name,
                    "source": str(source),
                    "destination": str(destination),
                    "bucket": "EXACT_DUPLICATE",
                    "event_id": ""
                })

                print(
                    f"  {duplicate_name} → "
                    f"{destination_folder.name}"
                )

    # ========================================
    # REPORT
    # ========================================

    report = pd.DataFrame(copied)

    report.to_csv(
        "final_copy_report.csv",
        index=False
    )

    print("\n" + "=" * 55)
    print("OUTPUT CREATED")
    print(f"Files copied: {len(report)}")
    print(f"Output: {OUTPUT_DIR}")
    print(
        f"Report: "
        f"{Path('final_copy_report.csv').resolve()}"
    )

    print("\nIMPORTANT:")
    print(
        "Input_Original was NOT moved, "
        "renamed or deleted."
    )


if __name__ == "__main__":
    main()