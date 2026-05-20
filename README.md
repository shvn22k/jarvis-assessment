# Boericke Homoeopathic Materia Medica Scraper

![Python](https://img.shields.io/badge/python-3.9%2B-blue) ![License](https://img.shields.io/badge/license-MIT-green) ![Tests](https://img.shields.io/badge/tests-48%20passing-brightgreen)

A production-grade Python scraper that crawls [Boericke's Homoeopathic Materia Medica](http://homeoint.org/books/boericmm/) and produces a structured JSON dataset powering the [jarvis.care](https://jarvis.care) AI clinical assistant.

---

## Background

Boericke's Materia Medica is one of the most referenced texts in homoeopathic medicine. It contains clinical monographs for hundreds of remedies organised alphabetically, each covering symptom profiles by organ system, dosing recommendations, and relationships to other remedies. Until now it existed only as an unstructured HTML website, making it inaccessible to programmatic search or AI analysis.

This scraper was built to change that. It crawls all 26 letter index pages, follows every remedy link, and extracts each page into a clean, validated JSON record — producing a dataset of 684 remedies that can be indexed, searched, and reasoned over by the jarvis.care clinical engine.

---

## Architecture

The scraper operates in two phases — crawling and extraction — followed by an enrichment pass on each record.

```
┌─────────────────────────────────────────────────────────┐
│                        scraper.py                        │
└─────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────┐
│   Phase 1: Crawl    │
│                     │
│  A.htm → B.htm →    │
│  ... → Z.htm        │     26 letter index pages
│                     │     ~30 remedy links each
│  parse_remedy_links │
└────────┬────────────┘
         │  684 (abbreviation, url) pairs
         ▼
┌─────────────────────┐
│  Phase 2: Extract   │
│                     │
│  fetch each remedy  │     retry + exponential backoff
│  parse_remedy_page  │     state-machine section parser
│                     │     handles 4 HTML variants
└────────┬────────────┘
         │  684 RemedyRecord dicts
         ▼
┌─────────────────────┐
│  Phase 3: Enrich    │
│                     │
│  extract_potencies  │     regex + named ordinal map
│  extract_keywords   │     token frequency + stopwords
│                     │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Atomic JSON Write  │     write → .tmp → os.replace()
│  boericke_          │     resumable: skip seen URLs
│  remedies.json      │     failed_urls.txt for errors
└─────────────────────┘
```

Each scraped record is written atomically using a `.tmp` file followed by `os.replace()`, so an interrupted run never leaves a corrupt output file. Resumability is built in — on restart, the scraper loads previously scraped URLs into a `seen_urls` set and skips them entirely. Retries use exponential backoff to handle transient network failures politely without hammering the server. The biggest technical challenge was that the source HTML has four distinct structural variants across the A–Z pages; the parser handles all of them through a dynamic container search (`name_p.parent`) rather than assuming a fixed page structure.

---

## Output Schema

Each remedy is stored as a JSON object with the following structure:

```json
{
  "abbreviation": "ABIES-C",
  "full_name": "ABIES CANADENSIS-PINUS CANADENSIS",
  "common_name": "Hemlock Spruce",
  "source_url": "http://homeoint.org/books/boericmm/a/abies-c.htm",
  "letter": "A",
  "general": "Mucous membranes are affected by Abies can...",
  "sections": {
    "Head": "Feels light-headed, tipsy. Irritable.",
    "Stomach": "Canine hunger with torpid liver...",
    "Dose": "First to third potency."
  },
  "relationships": null,
  "potencies": ["1c", "3c"],
  "keywords": ["mucous", "gastric", "catarrhal", "cravings", "uterine",
               "chilly", "sensations", "debility", "respiration", "liver"]
}
```

| Field | Type | Notes |
|---|---|---|
| `abbreviation` | string | Uppercase index abbreviation |
| `full_name` | string | Full Latin remedy name |
| `common_name` | string \| null | English name; null if not on the page |
| `source_url` | string | Canonical URL of the remedy page |
| `letter` | string | Single uppercase letter A–Z |
| `general` | string | Introductory text before the first section heading |
| `sections` | object | Section name → full text, e.g. Head, Stomach, Dose |
| `relationships` | string \| null | Cross-references to related remedies |
| `potencies` | array | Normalised potency tokens from the Dose section |
| `keywords` | array | Top 10 symptom keywords ranked by frequency |

---

## Setup

#### Prerequisites
- Python 3.9+
- Git

#### Installation

```bash
git clone https://github.com/shvn22k/jarvis-assessment.git
cd jarvis-assessment
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Verify:
```bash
python -c "import requests; import bs4; import lxml; print('All dependencies OK')"
```

---

## Usage

#### Scrape all A–Z
```bash
python scraper.py
```
Estimated time: 45–60 minutes for the full 684-remedy dataset.

#### Scrape a subset of letters
```bash
python scraper.py --letters A,B,C
```

#### Resume an interrupted run
The scraper is fully resumable. Re-run the same command — already-scraped URLs are detected from the existing output file and skipped automatically:
```bash
python scraper.py
```

#### Custom output path
```bash
python scraper.py --output my_output.json
```

#### Adjust request delay
The default delay is 0.5–1.0 seconds between requests. Increase it to be more conservative with the server:
```bash
python scraper.py --delay-min 1.0 --delay-max 2.0
```

#### All options
```bash
python scraper.py --help
```

| Argument | Default | Description |
|---|---|---|
| `--letters` | A–Z | Comma-separated letters to scrape |
| `--output` | `boericke_remedies.json` | Output file path |
| `--delay-min` | `0.5` | Minimum seconds between requests |
| `--delay-max` | `1.0` | Maximum seconds between requests |

---

## Running the Tests

The project includes 48 tests across 8 classes — 38 unit tests that run instantly without network access, and 10 integration tests that validate against the live website.

#### Unit tests only
```bash
# Command Prompt
set SKIP_INTEGRATION=1 && python -m unittest tests/test_scraper.py -v

# PowerShell
$env:SKIP_INTEGRATION="1"; python -m unittest tests/test_scraper.py -v
```

#### Full suite
```bash
python -m unittest tests/test_scraper.py -v
```

#### Test coverage

| Class | Type | Tests | Covers |
|---|---|---|---|
| `TestCleanText` | Unit | 6 | Whitespace normalisation, punctuation |
| `TestExtractPotencies` | Unit | 9 | Named ordinals, numeric tokens, dedup |
| `TestExtractKeywords` | Unit | 6 | Frequency ranking, stopword filtering |
| `TestParseRemedyLinks` | Unit | 7 | Nav exclusion, dedup, absolute URLs |
| `TestSaveAndLoadOutput` | Unit | 7 | Round-trip, resumability, atomic write |
| `TestLogFailedUrl` | Unit | 3 | Write, append, never-raises guarantee |
| `TestFetchPageIntegration` | Integration | 3 | Real fetch, 404 handling |
| `TestParseRemedyPageIntegration` | Integration | 7 | All 4 HTML variants |

---

## Project Structure

```
jarvis-assessment/
├── scraper.py               # Scraper — HTTP, parsing, enrichment, CLI
├── requirements.txt         # Pinned dependencies
├── README.md                # This file
├── sample_output.json       # 3 representative records for review
├── boericke_remedies.json   # Full 684-remedy dataset (not committed)
├── failed_urls.txt          # 4 URLs that failed to parse (not committed)
├── tests/
│   └── test_scraper.py      # 48-test suite (unit + integration)
└── prompts/                 # Phase-by-phase implementation prompts
```

---

## Known Limitations

Four remedies failed to parse — CON, GET, GLON, and MENTHO. Their pages fetch successfully but use an HTML structure not seen elsewhere in the dataset. They are logged in `failed_urls.txt`. The remaining 684 records are complete and fully validated.

The scraper targets a single static website that has not changed significantly in years. If the site structure changes, the parser will need to be updated. The modular function design makes this straightforward — `parse_remedy_page` is isolated and can be updated independently of the rest of the pipeline.

---

## Notes

- The 0.5–1.0s request delay is intentional — please do not remove it.
- `boericke_remedies.json` and `failed_urls.txt` are excluded from git and should be submitted separately as required by the assignment.
- Built for the jarvis.care engineering team as a hiring assessment submission.
