from pathlib import Path
from datetime import timedelta
import pandas as pd

METADATA_FILE = Path("photo_metadata_v2.csv")
DUPLICATE_FILE = Path("duplicate_report.csv")

# Nếu hai ảnh cách nhau hơn 4 giờ → bắt đầu event mới
EVENT_GAP_HOURS = 4


def choose_duplicate_exclusions():
    """
    Không xóa duplicate.
    Chỉ chọn 1 file đại diện trong mỗi duplicate group để clustering.
    Ưu tiên file không có '(1)' trong tên.
    """
    if not DUPLICATE_FILE.exists():
        return set()

    dup = pd.read_csv(DUPLICATE_FILE)

    excluded = set()

    for _, group in dup.groupby("duplicate_group"):

        names = group["file_name"].tolist()

        # Ưu tiên file không phải bản Windows/Drive rename "(1)"
        names_sorted = sorted(
            names,
            key=lambda x: (
                "(1)" in x,
                len(x),
                x.lower()
            )
        )

        keeper = names_sorted[0]

        for name in names_sorted[1:]:
            excluded.add(name)

        print(f"Duplicate keeper: {keeper}")

    return excluded


def main():

    print("\nPartner Visa Photo AI - Event Clustering")
    print("----------------------------------------")

    df = pd.read_csv(METADATA_FILE)

    excluded_duplicates = choose_duplicate_exclusions()

    # Loại duplicate khỏi xử lý logic, KHÔNG xóa file thật
    df["duplicate_excluded"] = df["file_name"].isin(
        excluded_duplicates
    )

    trusted = df[
        (df["trusted_capture_date"] == True)
        & (~df["duplicate_excluded"])
    ].copy()

    unknown = df[
        (df["trusted_capture_date"] != True)
        & (~df["duplicate_excluded"])
    ].copy()

    trusted["captured_at"] = pd.to_datetime(
        trusted["captured_at"]
    )

    trusted = trusted.sort_values("captured_at")

    event_ids = []

    current_event = 1
    previous_time = None

    gap_limit = timedelta(hours=EVENT_GAP_HOURS)

    for _, row in trusted.iterrows():

        current_time = row["captured_at"]

        if previous_time is not None:

            gap = current_time - previous_time

            if gap > gap_limit:
                current_event += 1

        event_ids.append(current_event)
        previous_time = current_time

    trusted["event_id"] = event_ids

    # Save detailed event membership
    trusted.to_csv(
        "event_clusters.csv",
        index=False
    )

    # Event summary
    summaries = []

    for event_id, group in trusted.groupby("event_id"):

        group = group.sort_values("captured_at")

        start = group["captured_at"].min()
        end = group["captured_at"].max()

        sample_names = group["file_name"].head(8).tolist()

        summaries.append({
            "event_id": event_id,
            "start_time": start,
            "end_time": end,
            "photo_count": len(group),
            "duration_hours": round(
                (end - start).total_seconds() / 3600,
                2
            ),
            "sample_files": " | ".join(sample_names)
        })

    summary_df = pd.DataFrame(summaries)

    summary_df.to_csv(
        "event_summary.csv",
        index=False
    )

    unknown.to_csv(
        "unknown_date_photos.csv",
        index=False
    )

    print("\n----------------------------------------")
    print("EVENT CLUSTERING COMPLETE")
    print(f"Original photos:          {len(df)}")
    print(f"Duplicate copies ignored: {len(excluded_duplicates)}")
    print(f"Trusted unique photos:    {len(trusted)}")
    print(f"Unknown-date photos:      {len(unknown)}")
    print(f"Candidate events:         {trusted['event_id'].nunique()}")

    print("\nFirst 20 candidate events:\n")

    print(
        summary_df[
            [
                "event_id",
                "start_time",
                "end_time",
                "photo_count",
                "duration_hours"
            ]
        ].head(20).to_string(index=False)
    )

    print("\nFiles created:")
    print(Path("event_clusters.csv").resolve())
    print(Path("event_summary.csv").resolve())
    print(Path("unknown_date_photos.csv").resolve())

    print("\nIMPORTANT:")
    print("No photos were moved, renamed or deleted.")


if __name__ == "__main__":
    main()