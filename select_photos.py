from pathlib import Path
import io
import re

import pandas as pd
import streamlit as st
from PIL import Image
from pillow_heif import register_heif_opener


register_heif_opener()

# =========================================================
# CONFIG
# =========================================================

OUTPUT_ROOT = Path(
    r"G:\My Drive\Le Minh Dang and Thi My Dung Tran - partner visa"
    r"\Photos and Messages\Photos\AI_OUTPUT_PREVIEW"
)

SELECTION_FILE = Path("word_photo_selection.csv")
NOTES_FILE = Path("event_notes.csv")

SUPPORTED = {
    ".jpg", ".jpeg", ".png",
    ".heic", ".heif", ".webp"
}

CATEGORY_MAP = {
    "01_SOCIAL": "Social",
    "02_HOUSEHOLD": "Nature of the Household",
    "99_REVIEW": "Review"
}

THUMBNAIL_MAX = 900
LARGE_PREVIEW_MAX = 1800


# =========================================================
# HELPERS
# =========================================================

def clean_event_name(folder_name):
    """
    Extract date + title if folder is:
    YYYY-MM-DD - Event Name
    """

    match = re.match(
        r"^(\d{4}-\d{2}-\d{2})\s*-\s*(.+)$",
        folder_name
    )

    if match:
        return match.group(1), match.group(2)

    return "", folder_name


def scan_events():

    events = []

    for folder_name, label in CATEGORY_MAP.items():

        category_path = OUTPUT_ROOT / folder_name

        if not category_path.exists():
            continue

        for event_folder in sorted(category_path.iterdir()):

            if not event_folder.is_dir():
                continue

            images = sorted([
    		p for p in event_folder.iterdir()
    		if p.suffix.lower() in SUPPORTED
	    ])

            if not images:
                continue

            event_date, event_title = clean_event_name(
                event_folder.name
            )

            events.append({
                "category_folder": folder_name,
                "category": label,
                "event_folder": event_folder,
                "event_name": event_folder.name,
                "event_date": event_date,
                "event_title": event_title,
                "images": images
            })

    return events


def load_selection():

    if not SELECTION_FILE.exists():
        return set()

    try:
        df = pd.read_csv(SELECTION_FILE)

        if "relative_path" not in df.columns:
            return set()

        return set(
            df["relative_path"]
            .dropna()
            .astype(str)
            .tolist()
        )

    except Exception:
        return set()


def save_all_selections(events, selected_paths):

    rows = []

    for event in events:

        selected_for_event = []

        for image in event["images"]:

            rel = str(
                image.relative_to(OUTPUT_ROOT)
            )

            if rel in selected_paths:
                selected_for_event.append(image)

        for order, image in enumerate(
            selected_for_event,
            start=1
        ):

            rows.append({
                "category": event["category"],
                "event_date": event["event_date"],
                "event_name": event["event_title"],
                "event_folder": event["event_name"],
                "file_name": image.name,
                "relative_path": str(
                    image.relative_to(OUTPUT_ROOT)
                ),
                "full_path": str(image),
                "order": order
            })

    columns = [
        "category",
        "event_date",
        "event_name",
        "event_folder",
        "file_name",
        "relative_path",
        "full_path",
        "order"
    ]

    pd.DataFrame(
        rows,
        columns=columns
    ).to_csv(
        SELECTION_FILE,
        index=False
    )


def load_notes():

    if not NOTES_FILE.exists():
        return {}

    try:

        df = pd.read_csv(
            NOTES_FILE,
            keep_default_na=False
        )

        result = {}

        for _, row in df.iterrows():

            result[str(row["event_folder"])] = {
                "facts": str(
                    row.get("facts", "")
                ),
                "wording_notes": str(
                    row.get("wording_notes", "")
                )
            }

        return result

    except Exception:
        return {}


def save_notes(notes):

    rows = []

    for event_folder, values in notes.items():

        rows.append({
            "event_folder": event_folder,
            "facts": values.get(
                "facts",
                ""
            ),
            "wording_notes": values.get(
                "wording_notes",
                ""
            )
        })

    pd.DataFrame(
        rows,
        columns=[
            "event_folder",
            "facts",
            "wording_notes"
        ]
    ).to_csv(
        NOTES_FILE,
        index=False
    )


@st.cache_data(show_spinner=False)
def make_preview(
    path_string,
    max_side=900,
    quality=88
):

    path = Path(path_string)

    with Image.open(path) as img:

        img.load()
        img = img.convert("RGB")

        img.thumbnail(
            (max_side, max_side),
            Image.Resampling.LANCZOS
        )

        buffer = io.BytesIO()

        img.save(
            buffer,
            format="JPEG",
            quality=quality
        )

        return buffer.getvalue()


def relative_path(image):

    return str(
        image.relative_to(OUTPUT_ROOT)
    )


def save_current_event_notes(
    event,
    facts,
    wording_notes
):

    st.session_state.notes[
        event["event_name"]
    ] = {
        "facts": facts,
        "wording_notes": wording_notes
    }


# =========================================================
# APP
# =========================================================

st.set_page_config(
    page_title="Partner Visa Photo Selector",
    layout="wide"
)

st.title("Partner Visa Photo Selector")

st.caption(
    "Choose the strongest photos for the Word evidence document. "
    "Nothing is moved, deleted or renamed."
)


events = scan_events()

if not events:

    st.error(
        f"No event folders found under:\n{OUTPUT_ROOT}"
    )

    st.stop()


# =========================================================
# SESSION STATE
# =========================================================

if "selected_paths" not in st.session_state:
    st.session_state.selected_paths = load_selection()

if "event_index" not in st.session_state:
    st.session_state.event_index = 0

if "notes" not in st.session_state:
    st.session_state.notes = load_notes()

if "viewer_index" not in st.session_state:
    st.session_state.viewer_index = None

if "current_event_identity" not in st.session_state:
    st.session_state.current_event_identity = None


# =========================================================
# SIDEBAR
# =========================================================

st.sidebar.header("Navigation")

category_filter = st.sidebar.selectbox(
    "Category",
    [
        "Social + Household",
        "Social only",
        "Household only",
        "Review only",
        "All"
    ]
)


if category_filter == "Social only":

    filtered_events = [
        e for e in events
        if e["category_folder"] == "01_SOCIAL"
    ]

elif category_filter == "Household only":

    filtered_events = [
        e for e in events
        if e["category_folder"] == "02_HOUSEHOLD"
    ]

elif category_filter == "Review only":

    filtered_events = [
        e for e in events
        if e["category_folder"] == "99_REVIEW"
    ]

elif category_filter == "Social + Household":

    filtered_events = [
        e for e in events
        if e["category_folder"] in {
            "01_SOCIAL",
            "02_HOUSEHOLD"
        }
    ]

else:

    filtered_events = events


if not filtered_events:

    st.warning(
        "No events in this category."
    )

    st.stop()


event_names = [
    f"{e['category']} | {e['event_name']}"
    for e in filtered_events
]


safe_index = min(
    st.session_state.event_index,
    len(event_names) - 1
)


selected_event_name = st.sidebar.selectbox(
    "Event",
    event_names,
    index=safe_index
)


event_index = event_names.index(
    selected_event_name
)

st.session_state.event_index = event_index

event = filtered_events[event_index]


# Reset large viewer when event changes
event_identity = str(
    event["event_folder"]
)

if (
    st.session_state.current_event_identity
    != event_identity
):

    st.session_state.current_event_identity = (
        event_identity
    )

    st.session_state.viewer_index = None


# =========================================================
# EVENT HEADER
# =========================================================

st.subheader(
    event["event_title"]
)


info_col1, info_col2, info_col3 = st.columns(3)


with info_col1:

    st.metric(
        "Category",
        event["category"]
    )


with info_col2:

    st.metric(
        "Date",
        event["event_date"] or "Unknown"
    )


with info_col3:

    selected_count = sum(
        1
        for image in event["images"]
        if relative_path(image)
        in st.session_state.selected_paths
    )

    st.metric(
        "Selected",
        f"{selected_count} / {len(event['images'])}"
    )


# =========================================================
# EVENT NOTES
# =========================================================

st.markdown(
    "### Event notes for caption drafting"
)


current_notes = st.session_state.notes.get(
    event["event_name"],
    {
        "facts": "",
        "wording_notes": ""
    }
)


facts = st.text_area(
    "Facts / context",
    value=current_notes.get(
        "facts",
        ""
    ),
    placeholder=(
        "Example: We prayed at the temple, "
        "had a vegetarian meal, and helped "
        "clean the temple grounds."
    ),
    help=(
        "Only add facts you know are true. "
        "These notes will later help draft "
        "the Word explanation."
    )
)


wording_notes = st.text_input(
    "Optional wording note",
    value=current_notes.get(
        "wording_notes",
        ""
    ),
    placeholder=(
        "Example: Mention that this was "
        "a peaceful day together."
    )
)


# =========================================================
# PHOTO SELECTION CONTROLS
# =========================================================

st.markdown(
    "### Select photos"
)

st.caption(
    "Choose different moments from the event "
    "rather than many nearly identical photos."
)


select_col, unselect_col, count_col = st.columns(
    [1, 1, 2]
)


with select_col:

    if st.button(
        "✓ Select all",
        width="stretch"
    ):

        for image in event["images"]:

            rel = relative_path(image)

            st.session_state.selected_paths.add(
                rel
            )

            st.session_state[
                f"check::{rel}"
            ] = True

        st.rerun()


with unselect_col:

    if st.button(
        "✕ Unselect all",
        width="stretch"
    ):

        for image in event["images"]:

            rel = relative_path(image)

            st.session_state.selected_paths.discard(
                rel
            )

            st.session_state[
                f"check::{rel}"
            ] = False

        st.rerun()


with count_col:

    selected_now = sum(
        1
        for image in event["images"]
        if relative_path(image)
        in st.session_state.selected_paths
    )

    st.info(
        f"Selected for this event: "
        f"{selected_now} / "
        f"{len(event['images'])}"
    )


# =========================================================
# LARGE PHOTO VIEWER
# =========================================================

if st.session_state.viewer_index is not None:

    if (
        st.session_state.viewer_index
        >= len(event["images"])
    ):

        st.session_state.viewer_index = 0


    viewer_index = (
        st.session_state.viewer_index
    )

    viewer_image = (
        event["images"][viewer_index]
    )

    viewer_rel = relative_path(
        viewer_image
    )


    st.divider()

    st.markdown(
        "## 🔍 Large Photo Viewer"
    )

    st.caption(
        f"{viewer_image.name}   •   "
        f"Photo {viewer_index + 1} "
        f"of {len(event['images'])}"
    )


    try:

        large_preview = make_preview(
            str(viewer_image),
            LARGE_PREVIEW_MAX,
            92
        )

        left_space, image_col, right_space = (
            st.columns([1, 6, 1])
        )

        with image_col:

            st.image(
                large_preview,
                width="stretch"
            )

    except Exception as exc:

        st.error(
            f"Cannot preview "
            f"{viewer_image.name}: {exc}"
        )


    previous_col, select_current_col, next_col, close_col = (
      st.columns([1, 2, 1, 1])
    )

    with previous_col:
        if st.button(
            "Previous",
            key="viewer_previous",
            shortcut="Left",
            width="stretch"
        ):
            st.session_state.viewer_index = (
                viewer_index - 1
            ) % len(event["images"])

            st.rerun()

    with select_current_col:
        currently_selected = (
            viewer_rel in st.session_state.selected_paths
        )

        if currently_selected:
            if st.button(
                "Selected - click to unselect",
                key="viewer_toggle_selected",
                width="stretch"
            ):
                st.session_state.selected_paths.discard(
                    viewer_rel
                )

                st.session_state[
                    f"check::{viewer_rel}"
                ] = False

                st.rerun()

        else:
            if st.button(
                "Select this photo",
                key="viewer_toggle_selected",
                type="primary",
                width="stretch"
            ):
                st.session_state.selected_paths.add(
                    viewer_rel
                )

                st.session_state[
                    f"check::{viewer_rel}"
                ] = True

                st.rerun()

    with next_col:
        if st.button(
            "Next",
            key="viewer_next",
            shortcut="Right",
            width="stretch"
        ):
            st.session_state.viewer_index = (
                viewer_index + 1
            ) % len(event["images"])

            st.rerun()

    with close_col:
        if st.button(
            "Close",
            key="viewer_close",
            width="stretch"
        ):
            st.session_state.viewer_index = None

            st.rerun()


    st.caption(
        "Previous and Next loop through all "
        "photos in this event so you can compare "
        "similar photos quickly."
    )

    st.divider()


# =========================================================
# PHOTO GRID
# =========================================================

cols_per_row = 3


for start in range(
    0,
    len(event["images"]),
    cols_per_row
):

    columns = st.columns(
        cols_per_row
    )

    batch = event["images"][
        start:start + cols_per_row
    ]


    for col, image in zip(
        columns,
        batch
    ):

        rel = relative_path(
            image
        )


        with col:

            try:

                preview = make_preview(
                    str(image),
                    THUMBNAIL_MAX,
                    88
                )

                st.image(
                    preview,
                    width="stretch"
                )

            except Exception as exc:

                st.error(
                    f"Cannot preview "
                    f"{image.name}\n{exc}"
                )


            checked = (
                rel
                in st.session_state.selected_paths
            )


            new_checked = st.checkbox(
                image.name,
                value=checked,
                key=f"check::{rel}"
            )


            if new_checked:

                st.session_state.selected_paths.add(
                    rel
                )

            else:

                st.session_state.selected_paths.discard(
                    rel
                )


            if st.button(
                "🔍 View large",
                key=f"view::{rel}",
                width="stretch"
            ):

                st.session_state.viewer_index = (
                    event["images"].index(image)
                )

                st.rerun()


# =========================================================
# SAVE + NAVIGATION
# =========================================================

st.divider()


left, middle, right = st.columns(
    [1, 2, 1]
)


with left:

    if st.button(
        "← Previous event",
        width="stretch",
        disabled=(
            event_index == 0
        )
    ):

        save_current_event_notes(
            event,
            facts,
            wording_notes
        )

        save_all_selections(
            events,
            st.session_state.selected_paths
        )

        save_notes(
            st.session_state.notes
        )

        st.session_state.viewer_index = None

        st.session_state.event_index = (
            event_index - 1
        )

        st.rerun()


with middle:

    if st.button(
        "💾 Save selection",
        type="primary",
        width="stretch"
    ):

        save_current_event_notes(
            event,
            facts,
            wording_notes
        )

        save_all_selections(
            events,
            st.session_state.selected_paths
        )

        save_notes(
            st.session_state.notes
        )

        st.success(
            "Saved successfully to "
            "word_photo_selection.csv "
            "and event_notes.csv"
        )


with right:

    if st.button(
        "Next event →",
        width="stretch",
        disabled=(
            event_index
            >= len(filtered_events) - 1
        )
    ):

        save_current_event_notes(
            event,
            facts,
            wording_notes
        )

        save_all_selections(
            events,
            st.session_state.selected_paths
        )

        save_notes(
            st.session_state.notes
        )

        st.session_state.viewer_index = None

        st.session_state.event_index = (
            event_index + 1
        )

        st.rerun()


# =========================================================
# SIDEBAR SUMMARY
# =========================================================

st.sidebar.divider()

st.sidebar.metric(
    "Total selected photos",
    len(
        st.session_state.selected_paths
    )
)

st.sidebar.caption(
    "Selections are stored locally. "
    "Original Google Drive photos are untouched."
)