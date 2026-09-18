import re
from pathlib import Path
import pandas as pd


METADATA_FILE = Path("photo_metadata_v2.csv")
UNKNOWN_FILE = Path("unknown_date_photos.csv")


def get_img_number(filename):
    match = re.search(r"IMG[_-](\d+)", str(filename), re.IGNORECASE)

    if match:
        return int(match.group(1))

    return None


def main():

    metadata = pd.read_csv(METADATA_FILE)

    trusted = metadata[
        metadata["trusted_capture_date"] == True
    ].copy()

    unknown = metadata[
        metadata["trusted_capture_date"] != True
    ].copy()

    trusted["img_number"] = trusted["file_name"].apply(
        get_img_number
    )

    unknown["img_number"] = unknown["file_name"].apply(
        get_img_number
    )

    trusted = trusted.dropna(
        subset=["img_number"]
    )

    trusted["img_number"] = trusted["img_number"].astype(int)

    print("\nUNKNOWN PHOTO NEIGHBOUR CHECK")
    print("=" * 65)

    rows = []

    for _, row in unknown.iterrows():

        file_name = row["file_name"]
        img_number = row["img_number"]

        print(f"\nUNKNOWN: {file_name}")

        if pd.isna(img_number):
            print("  Cannot extract IMG number.")
            continue

        img_number = int(img_number)

        candidates = trusted.copy()

        candidates["distance"] = (
            candidates["img_number"] - img_number
        ).abs()

        nearest = candidates.sort_values(
            ["distance", "img_number"]
        ).head(6)

        for _, neighbour in nearest.iterrows():

            print(
                f"  {neighbour['file_name']:<25}"
                f" number={int(neighbour['img_number']):<6}"
                f" date={neighbour['captured_at']}"
            )

            rows.append({
                "unknown_file": file_name,
                "unknown_img_number": img_number,
                "neighbour_file": neighbour["file_name"],
                "neighbour_img_number":
                    int(neighbour["img_number"]),
                "distance": int(neighbour["distance"]),
                "neighbour_date": neighbour["captured_at"]
            })

    output = pd.DataFrame(rows)

    output.to_csv(
        "unknown_neighbors.csv",
        index=False
    )

    print("\n" + "=" * 65)
    print("COMPLETE")
    print("Saved: unknown_neighbors.csv")


if __name__ == "__main__":
    main()