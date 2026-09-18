import os
import io
import json
import time
from pathlib import Path

import pandas as pd
from PIL import Image
from pillow_heif import register_heif_opener
from dotenv import load_dotenv
from google import genai
from google.genai import types

register_heif_opener()

MODEL_NAME = "gemini-3.7-flash"

UNKNOWN_FILE = Path("unknown_date_photos.csv")
EVENT_CLASSIFICATION_FILE = Path("event_classification.csv")
OUTPUT_FILE = Path("unknown_photo_classification.csv")

PHOTO_DIR = Path(
    r"G:\My Drive\Le Minh Dang and Thi My Dung Tran - partner visa\Photos and Messages\Photos\Input_Original"
)

MAX_IMAGE_SIDE = 1280
JPEG_QUALITY = 80


def image_to_jpeg_bytes(path):
    with Image.open(path) as img:
        img.load()
        img = img.convert("RGB")

        w, h = img.size
        largest = max(w, h)

        if largest > MAX_IMAGE_SIDE:
            ratio = MAX_IMAGE_SIDE / largest
            img = img.resize(
                (round(w * ratio), round(h * ratio)),
                Image.Resampling.LANCZOS
            )

        buffer = io.BytesIO()
        img.save(
            buffer,
            format="JPEG",
            quality=JPEG_QUALITY,
            optimize=True
        )

        return buffer.getvalue()


def main():
    load_dotenv()

    client = genai.Client(
        api_key=os.getenv("GEMINI_API_KEY")
    )

    unknown = pd.read_csv(UNKNOWN_FILE)
    events = pd.read_csv(EVENT_CLASSIFICATION_FILE)

    event_reference = "\n".join(
        f"Event {row.event_id}: "
        f"{row.primary_bucket} - {row.event_name}"
        for _, row in events.iterrows()
    )

    results = []

    print("\nUNKNOWN PHOTO CLASSIFICATION")
    print("=" * 50)
    print(f"Unknown photos: {len(unknown)}\n")

    for index, row in unknown.iterrows():

        filename = row["file_name"]
        path = PHOTO_DIR / filename

        print(
            f"[{index + 1}/{len(unknown)}] "
            f"{filename}"
        )

        try:
            image_bytes = image_to_jpeg_bytes(path)

            image_part = types.Part.from_bytes(
                data=image_bytes,
                mime_type="image/jpeg"
            )

            prompt = f"""
This image belongs to an Australian Partner Visa
relationship evidence set.

The capture date is unavailable.

Classify the image into:

SOCIAL
- family/friends
- birthdays
- wedding
- restaurants
- travel
- outings
- celebrations
- social/public activities

HOUSEHOLD
- shared home life
- cooking
- groceries
- chores
- household activities
- living together
- home setup

REVIEW
- unclear
- document/screenshot
- cannot confidently classify

Existing candidate events already identified:

{event_reference}

Tasks:

1. Determine SOCIAL, HOUSEHOLD or REVIEW.
2. Give a short factual description of the image.
3. Decide whether it appears to clearly match one of the
   existing events above.
4. Only suggest an existing event_id if the visual context
   strongly supports it.
5. Do NOT guess a date.
6. If uncertain, set matching_event_id to null.

Return strict JSON:

{{
  "primary_bucket": "SOCIAL",
  "description": "short description",
  "confidence": 0.90,
  "matching_event_id": null,
  "matching_confidence": 0.0,
  "reason": "brief reason"
}}
"""

            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=[
                    image_part,
                    types.Part.from_text(text=prompt)
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    thinking_config=types.ThinkingConfig(
                        thinking_level="low"
                    )
                )
            )

            data = json.loads(response.text)

            result = {
                "file_name": filename,
                "primary_bucket":
                    data.get("primary_bucket", "REVIEW"),
                "description":
                    data.get("description", ""),
                "confidence":
                    data.get("confidence", 0),
                "matching_event_id":
                    data.get("matching_event_id"),
                "matching_confidence":
                    data.get("matching_confidence", 0),
                "reason":
                    data.get("reason", "")
            }

            results.append(result)

            print(
                f"    -> {result['primary_bucket']} | "
                f"{result['description']} | "
                f"match={result['matching_event_id']}"
            )

        except Exception as e:

            print(f"    ERROR: {e}")

            results.append({
                "file_name": filename,
                "primary_bucket": "REVIEW",
                "description": "API/read error",
                "confidence": 0,
                "matching_event_id": None,
                "matching_confidence": 0,
                "reason": str(e)
            })

        time.sleep(1)

    output = pd.DataFrame(results)
    output.to_csv(OUTPUT_FILE, index=False)

    print("\n" + "=" * 50)
    print("COMPLETE")
    print(f"Saved: {OUTPUT_FILE.resolve()}")

    print("\nResults:")
    print(
        output[
            [
                "file_name",
                "primary_bucket",
                "description",
                "matching_event_id",
                "matching_confidence"
            ]
        ].to_string(index=False)
    )


if __name__ == "__main__":
    main()