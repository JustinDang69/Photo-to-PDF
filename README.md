# Privacy-Aware Photo Evidence Processing & Document Automation

A Python-based automation pipeline developed to reduce the repetitive work involved in preparing large collections of photographic evidence for professional review.

The project originated from a **real law-firm workflow**, where large collections of client photos needed to be reviewed, dated, checked for duplicates, grouped into events, described, selected and converted into structured documents.

The goal is not to replace professional judgement.

Instead, the system automates repetitive preparation so that human reviewers can focus on the quality, relevance and accuracy of the evidence.

---

## The Problem

Preparing large collections of photographic evidence manually can require:

- opening hundreds of images
- determining when each image was captured
- identifying duplicates
- detecting visually similar images
- grouping photos into meaningful events
- writing descriptions
- categorising events
- selecting representative photos
- organising files
- generating Word documents
- revising documents after professional review
- generating final PDFs
- meeting page-count and file-size requirements

This becomes increasingly time-consuming and inconsistent as the number of photos grows.

---

## Solution

The project creates an automated pipeline that transforms an unstructured photo collection into a structured starting point for professional review.

```text
Client Photo Collection
        ↓
Metadata & EXIF Scan
        ↓
Duplicate Detection
        ↓
Visual Similarity Analysis
        ↓
Event Clustering
        ↓
AI-Assisted Image Analysis
        ↓
Event Classification
        ↓
Confidence-Based Review
        ↓
Human Photo Selection
        ↓
Word Draft Generation
        ↓
Professional Review
        ↓
PDF Export & Validation
```

---

## How It Helped in Practice

The system was used as part of a real operational law-firm workflow.

Rather than beginning with an unstructured photo folder, the workflow can automatically prepare information including:

- trusted capture dates
- duplicate-photo candidates
- visually similar images
- possible event groupings
- factual image descriptions
- event categories
- confidence scores
- uncertain cases requiring review
- structured photo selections
- draft evidence documents

This shifts human effort away from repetitive file handling and toward reviewing whether the evidence is accurate, relevant and suitable.

---

## Current Architecture

The current implementation combines traditional local processing with selected AI-assisted visual analysis.

### Local Processing

The following stages are performed locally:

- file discovery
- EXIF metadata extraction
- trusted capture-date detection
- duplicate detection
- visual similarity analysis
- event clustering
- file organisation
- human review
- photo selection
- Word document generation
- PDF conversion
- PDF splitting and compression
- final-output validation

### AI-Assisted Processing

The current prototype uses a vision-capable **Gemini API** for selected image-analysis tasks.

The AI can generate:

- factual image descriptions
- suggested event names
- event classifications
- confidence scores

Low-confidence or uncertain results are routed to human review rather than being automatically accepted.

---

## Main Workflow

### 1. Photo Metadata Scanning

The system scans common image formats and extracts available metadata.

Supported processing includes formats such as:

- JPEG / JPG
- PNG
- HEIC / HEIF
- WebP

Where available, trusted EXIF fields such as capture date are prioritised over less reliable filesystem timestamps.

---

### 2. Duplicate Detection

The workflow checks for duplicated or near-duplicated images.

This reduces repeated evidence and allows reviewers to focus on representative photos.

The project includes both:

- exact / metadata-based duplicate checks
- visual similarity processing

---

### 3. Event Clustering

Photos are grouped into possible events based on available information such as:

- capture timing
- neighbouring photos
- similarity
- existing event context

These clusters form the basis for later classification and description.

---

### 4. AI-Assisted Image Understanding

Representative or uncertain images can be analysed using a vision model.

The model is used to generate structured information rather than make final decisions.

Example outputs include:

```text
Event:
Family gathering

Description:
Several people seated together at a dining table in an indoor setting.

Category:
SOCIAL

Confidence:
0.87
```

The system is designed to avoid inventing dates or identifying people.

---

## Confidence-Based Review

AI results are not automatically treated as correct.

A confidence threshold is used to separate results into:

```text
High Confidence
      ↓
Continue Through Workflow

Low Confidence / Ambiguous
      ↓
REVIEW
      ↓
Human Decision
```

This creates a **human-in-the-loop** workflow.

---

## Human Review

Human review remains a required part of the system.

The reviewer can:

- inspect event groups
- check generated descriptions
- reject incorrect classifications
- review uncertain images
- select representative photos
- control what is included in the final document

The AI acts as a workflow assistant rather than the final decision-maker.

---

## Document Automation

After photo review, the system can generate structured evidence documents.

The workflow supports:

- selected-photo placement
- event headings
- photo descriptions
- Word document generation
- review-ready drafts
- approved-document conversion
- final PDF generation

This connects image processing directly with document preparation.

---

## PDF Processing

The final stage focuses on producing practical submission-ready documents.

The pipeline can:

- convert approved Word documents to PDF
- split oversized documents
- limit page counts
- compress image-heavy PDFs
- validate final file sizes
- verify generated documents

The original approved source documents are not modified.

---

## Repository Components

### `scan_photos_v2.py`

Scans photo collections and extracts trusted metadata.

### `check_duplicates.py`

Checks for duplicate records or images.

### `find_visual_duplicates.py`

Identifies visually similar photo candidates.

### `cluster_events.py`

Groups photos into possible events.

### `classify_events.py`

Uses AI-assisted visual analysis to classify events and generate structured descriptions.

### `classify_unknown_photos.py`

Analyses photos that could not confidently be assigned during earlier processing.

### `inspect_unknown_neighbors.py`

Provides additional context for uncertain photos using neighbouring items.

### `select_photos.py`

Supports human review and final photo selection.

### `build_word_drafts_v4_3_resume.py`

Generates structured Word-document drafts from reviewed photo evidence.

### `export_approved_pdfs.py`

Converts reviewed documents into final PDFs and applies page/file-size validation.

### `lodgement_merge.py`

Supports final document assembly.

### `organize_output.py`

Organises generated workflow outputs.

---

## Technologies

### Programming & Data

- Python
- Pandas
- pathlib
- CSV processing

### Image Processing

- Pillow
- pillow-heif
- EXIF metadata
- visual similarity analysis

### AI / Computer Vision

- Gemini Vision API — current prototype
- vision-language modelling
- structured AI output
- confidence-based classification

### Documents

- Microsoft Word automation
- LibreOffice
- PyMuPDF
- PDF conversion
- PDF splitting
- PDF compression
- document validation

### Workflow Design

- human-in-the-loop review
- confidence thresholds
- non-destructive processing
- intermediate workflow records

---

## Privacy Limitation Identified

The current prototype demonstrated that external vision APIs can significantly reduce manual image-review work.

However, the project also revealed an important architectural issue.

Photographic evidence can contain highly sensitive client information.

When raw images are sent to an external AI service, the application owner has less control over where and how those images are processed.

Even where an external provider has strong privacy and security protections, reducing unnecessary third-party exposure is preferable for sensitive workflows.

This led to the next stage of the project.

---

## Phase 2 — Local Vision Model

The planned next stage replaces external raw-image analysis with a **pre-trained vision or vision-language model running locally or within controlled infrastructure**.

The goal is for the model to scan each image and automatically produce a factual caption or structured visual description without requiring the raw photo to be sent to an external AI service.

### Target Architecture

```text
Client Photos
      ↓
Local EXIF / Metadata Scan
      ↓
Duplicate & Similarity Detection
      ↓
Local Pre-Trained Vision Model
      ↓
Automatic Photo Caption
      ↓
Event Clustering & Classification
      ↓
Human Review
      ↓
Photo Selection
      ↓
Word Draft Generation
      ↓
Professional Review
      ↓
Final PDF Export
```

Example local-model output:

```text
Photo Caption:
Three adults standing together outdoors in front of a restaurant.

Possible Event:
Dinner gathering

Confidence:
0.91
```

The generated captions can then feed the existing event-classification and document-processing pipeline.

---

## Why Move Toward Local AI?

The change is not simply about replacing one model with another.

It is an architectural decision based on data sensitivity.

Potential advantages include:

- reduced transmission of raw client images
- greater control over where processing occurs
- reduced dependency on third-party AI infrastructure
- improved data-governance options
- ability to run workflows in controlled environments

The trade-offs include:

- local hardware requirements
- inference speed
- model size
- deployment complexity
- potentially lower capability than large hosted models

These trade-offs will be evaluated during Phase 2.

---

## Project Status

### Phase 1 — Working Prototype

- ✅ photo metadata scanning
- ✅ trusted EXIF date extraction
- ✅ duplicate detection
- ✅ visual similarity processing
- ✅ event clustering
- ✅ Gemini-assisted image analysis
- ✅ automatic event descriptions
- ✅ event classification
- ✅ confidence-based review
- ✅ human photo selection
- ✅ Word draft generation
- ✅ PDF generation
- ✅ PDF splitting and compression
- ✅ final-output validation

### Phase 2 — Planned

- 🔄 evaluate suitable pre-trained vision-language models
- 🔄 test local image caption generation
- 🔄 compare local-model accuracy with the current API workflow
- 🔄 integrate local captions into event classification
- 🔄 benchmark inference speed and hardware requirements
- 🔄 evaluate deployment and privacy trade-offs
- 🔄 reduce reliance on external raw-image analysis

---

## Key Engineering Lessons

This project demonstrated that solving a real workflow problem requires more than simply integrating an AI API.

Important engineering challenges included:

- working with unstructured real-world files
- incomplete or unreliable metadata
- duplicate detection
- visual similarity
- image understanding
- uncertain predictions
- human review
- document-generation constraints
- PDF limits
- workflow reliability
- privacy and data governance

One of the most important lessons was:

> A technically successful AI system may still require architectural redesign when it is applied to sensitive real-world data.

---

## Real-World Value

The main value of the system is not replacing professional judgement.

It is reducing repetitive preparation work.

Instead of spending the majority of time opening, sorting and organising individual images, the system prepares a structured starting point that can then be reviewed by a human professional.

This allows more effort to be spent on:

- evidence quality
- relevance
- accuracy
- final professional decisions

---

## Limitations

The current prototype has several limitations:

- AI classifications may be incorrect
- metadata may be missing
- visually similar photos may not always belong to the same event
- external AI processing remains part of the current prototype
- local vision-model performance still needs evaluation
- professional review remains necessary

---

## Disclaimer

This project demonstrates workflow automation, computer vision and document-processing techniques.

It does not provide legal advice and does not replace professional review.

No real client photographs or case documents are included in this public repository.

---

## Author

**Justin Dang**

Data Analytics • Data Science • Automation
