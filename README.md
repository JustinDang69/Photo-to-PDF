# Privacy-Aware Photo Evidence Processing & Document Automation

A Python-based automation pipeline developed to reduce the manual work involved in preparing large collections of photographic evidence for legal and immigration matters.

The project was developed from a real workflow problem encountered in a law-firm environment: large volumes of client photos had to be reviewed, dated, grouped into meaningful events, checked for duplicates, described, selected and eventually assembled into structured documents for professional review.

## The Real-World Problem

Preparing photographic evidence manually can involve repetitive work such as:

- opening hundreds of photos individually
- determining when each photo was taken
- identifying duplicate or near-duplicate images
- deciding which photos belong to the same event
- describing the context shown in each photo
- separating different evidence categories
- choosing representative photos
- organising them into folders
- building Word documents
- revising the documents after professional review
- converting the final approved documents into PDFs that meet submission limits

Doing this manually is time-consuming and makes it easy to lose consistency when the number of photos becomes large.

This project was built to automate much of that workflow while keeping a human reviewer in control of the final evidence.

## How It Helped in Practice

The system was used as part of a real law-firm workflow to assist with organising client photographic evidence.

Instead of manually inspecting and organising every image from the beginning, the pipeline could first process the collection automatically and prepare a structured starting point for review.

For example, the workflow can:

1. scan the client's photo collection
2. extract reliable capture dates from image metadata
3. identify duplicates and visually similar photos
4. group photos that appear to belong to the same event
5. analyse representative photos
6. generate short factual descriptions of the events
7. organise events into relevant evidence categories
8. flag uncertain results for manual review
9. allow a person to select the strongest photos
10. generate structured Word drafts
11. convert approved documents into submission-ready PDFs

This does not replace the lawyer or professional reviewer.

Instead, it reduces repetitive preparation work so that more time can be spent reviewing the quality and relevance of the evidence.

## Current Architecture

The current prototype combines traditional Python processing with a vision-capable AI model.

### Local processing

Several operations happen locally:

- EXIF metadata extraction
- trusted capture-date detection
- duplicate detection
- visual similarity checking
- event clustering
- file organisation
- human review
- document generation
- PDF conversion, splitting and compression

### Current AI processing

For the current prototype, selected representative photos are sent to the Gemini API.

The vision model analyses the images and can automatically generate information such as:

- a factual description of the scene
- an event classification
- a suggested event name
- a confidence score

Low-confidence results are not automatically accepted and are instead sent to a human-review stage.

## Privacy Limitation Discovered

The first version proved that AI vision can significantly reduce manual photo-review work.

However, it also exposed an important architectural problem.

Legal and immigration evidence may contain highly sensitive client photos.

When an external AI API is used for visual analysis, raw client images leave the local environment and are processed by infrastructure that the application owner does not fully control.

Even when a provider has privacy and security safeguards, this is not the architecture I want to rely on long term for confidential client material.

This became one of the most important lessons from the project:

> A solution can work technically while still needing improvement from a privacy and data-governance perspective.

## Next Stage — Local Pre-Trained Vision Model

The next stage of the project is therefore focused on privacy-preserving AI.

Instead of uploading raw client photos to an external generative-AI service, the plan is to use a **pre-trained vision or vision-language model running locally or within controlled infrastructure**.

The model will scan each image and automatically generate a factual caption or structured visual description.

The caption can then be used by the remaining classification and document-processing pipeline.

### Planned Architecture

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
