from pathlib import Path
import pandas as pd
from PIL import Image
from pillow_heif import register_heif_opener
import imagehash

register_heif_opener()

PHOTO_DIR = Path(
    r"G:\My Drive\Le Minh Dang and Thi My Dung Tran - partner visa\Photos and Messages\Photos\Input_Original"
)

TARGETS = [
    "IMG_9006.PNG",
    "IMG_9007.PNG",
    "IMG_9008.PNG",
]

SUPPORTED = {
    ".jpg", ".jpeg", ".png",
    ".heic", ".heif", ".webp"
}

TOP_MATCHES = 8


def center_crop(img, ratio):
    """
    Crop the centre of the image.
    Useful because screenshots may contain borders/UI around the original photo.
    """
    w, h = img.size

    new_w = int(w * ratio)
    new_h = int(h * ratio)

    left = (w - new_w) // 2
    top = (h - new_h) // 2

    return img.crop(
        (left, top, left + new_w, top + new_h)
    )


def make_hashes(path):
    """
    Generate multiple perceptual hashes from:
    - full image
    - 90% centre crop
    - 80% centre crop
    - 70% centre crop
    """

    with Image.open(path) as img:
        img.load()
        img = img.convert("RGB")

        variants = [
            img,
            center_crop(img, 0.90),
            center_crop(img, 0.80),
            center_crop(img, 0.70),
        ]

        hashes = []

        for variant in variants:
            hashes.append(
                imagehash.phash(
                    variant,
                    hash_size=8
                )
            )

        return hashes


def best_distance(target_hashes, candidate_hashes):
    """
    Smaller = more visually similar.
    0 means essentially identical perceptual hash.
    """
    return min(
        t - c
        for t in target_hashes
        for c in candidate_hashes
    )


def distance_label(distance):
    if distance <= 4:
        return "VERY STRONG"
    elif distance <= 8:
        return "STRONG"
    elif distance <= 12:
        return "POSSIBLE"
    elif distance <= 16:
        return "WEAK"
    else:
        return "UNLIKELY"


def main():

    files = [
        p for p in PHOTO_DIR.iterdir()
        if p.is_file()
        and p.suffix.lower() in SUPPORTED
    ]

    print("\nVISUAL DUPLICATE SEARCH")
    print("=" * 70)
    print(f"Photos available: {len(files)}")

    # Optional metadata/report enrichment
    metadata = None
    copy_report = None

    if Path("photo_metadata_v2.csv").exists():
        metadata = pd.read_csv("photo_metadata_v2.csv")

    if Path("final_copy_report.csv").exists():
        copy_report = pd.read_csv("final_copy_report.csv")

    print("\nCalculating candidate image hashes...")

    candidate_hashes = {}

    for index, path in enumerate(files, start=1):

        if path.name in TARGETS:
            continue

        try:
            candidate_hashes[path.name] = make_hashes(path)
        except Exception as e:
            print(
                f"WARNING cannot read {path.name}: {e}"
            )

        if index % 50 == 0:
            print(f"  processed {index}/{len(files)}")

    all_results = []

    for target_name in TARGETS:

        target_path = PHOTO_DIR / target_name

        print("\n" + "=" * 70)
        print(f"TARGET: {target_name}")

        if not target_path.exists():
            print("TARGET FILE NOT FOUND")
            continue

        target_hashes = make_hashes(target_path)

        matches = []

        for candidate_name, hashes in candidate_hashes.items():

            distance = best_distance(
                target_hashes,
                hashes
            )

            matches.append({
                "target": target_name,
                "candidate": candidate_name,
                "phash_distance": distance,
                "match_strength":
                    distance_label(distance),
            })

        matches = sorted(
            matches,
            key=lambda x: x["phash_distance"]
        )[:TOP_MATCHES]

        for rank, match in enumerate(matches, start=1):

            candidate = match["candidate"]

            captured_at = ""
            bucket = ""
            event_id = ""
            destination = ""

            if metadata is not None:
                m = metadata[
                    metadata["file_name"] == candidate
                ]

                if not m.empty:
                    captured_at = str(
                        m.iloc[0]["captured_at"]
                    )

            if copy_report is not None:
                r = copy_report[
                    copy_report["file_name"] == candidate
                ]

                if not r.empty:
                    bucket = str(
                        r.iloc[0]["bucket"]
                    )
                    event_id = str(
                        r.iloc[0]["event_id"]
                    )
                    destination = str(
                        r.iloc[0]["destination"]
                    )

            print(
                f"\n#{rank} {candidate}"
            )
            print(
                f"   pHash distance: "
                f"{match['phash_distance']} "
                f"({match['match_strength']})"
            )

            if captured_at:
                print(
                    f"   captured_at: {captured_at}"
                )

            if bucket:
                print(
                    f"   output: {bucket} "
                    f"| event {event_id}"
                )

            if destination:
                print(
                    f"   destination: {destination}"
                )

            all_results.append({
                **match,
                "rank": rank,
                "captured_at": captured_at,
                "bucket": bucket,
                "event_id": event_id,
                "destination": destination,
            })

    pd.DataFrame(all_results).to_csv(
        "visual_duplicate_results.csv",
        index=False
    )

    print("\n" + "=" * 70)
    print("SEARCH COMPLETE")
    print(
        "Saved: visual_duplicate_results.csv"
    )
    print("\nNo files were changed or deleted.")


if __name__ == "__main__":
    main()