"""
Boericke Homoeopathic Materia Medica Scraper
=============================================
Scrapes the full text of Boericke's Homoeopathic Materia Medica from
http://homeoint.org/books/boericmm/ and outputs a clean, structured
JSON dataset for use in the jarvis.care AI clinical assistant.

Author: github.com/shvn22k
"""

import argparse
import json
import logging
import os
import random
import re
import sys
import time
from collections import Counter
from typing import Dict, List, Optional, Set, Tuple, TypedDict
from urllib.parse import urljoin

import pymongo
import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

BASE_URL: str = "http://homeoint.org/books/boericmm/"
LETTERS: List[str] = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
OUTPUT_FILE: str = "boericke_remedies.json"
FAILED_FILE: str = "failed_urls.txt"
DELAY_MIN: float = 0.5
DELAY_MAX: float = 1.0
REQUEST_TIMEOUT: int = 15
MAX_RETRIES: int = 3

NAMED_POTENCIES: Dict[str, str] = {
    "first": "1c",
    "second": "2c",
    "third": "3c",
    "sixth": "6c",
    "thirtieth": "30c",
    "two-hundredth": "200c",
    "two hundredth": "200c",
}

STOPWORDS: Set[str] = {
    "with", "from", "that", "this", "which", "have", "been",
    "when", "also", "than", "into", "more", "after", "upon",
    "will", "very", "much", "some", "over", "such", "both",
    "each", "most", "here", "they", "them", "their", "there",
    "then", "what", "like", "only", "even", "well", "does",
    "left", "side", "pain", "worse", "better", "especially",
}

session = requests.Session()
session.headers.update(
    {"User-Agent": "Mozilla/5.0 (compatible; BoerickeBot/1.0; +https://jarvis.care)"}
)


class RemedyRecord(TypedDict):
    abbreviation: str
    full_name: str
    common_name: Optional[str]
    source_url: str
    letter: str
    general: str
    sections: Dict[str, str]
    relationships: Optional[str]
    potencies: List[str]
    keywords: List[str]

def fetch_page(url: str, retries: int = MAX_RETRIES) -> Optional[str]:
    """
    Fetch the raw HTML of a URL with retry logic and exponential backoff.

    Uses the module-level shared session for all requests. Retries only on
    network/timeout errors — HTTP error responses (4xx, 5xx) are not retried
    since retrying them will not change the outcome.

    Args:
        url:     The full URL to fetch.
        retries: Number of retry attempts on transient network errors.
                 Defaults to MAX_RETRIES. Does not apply to HTTP errors.

    Returns:
        Raw HTML string on success, or None if the request failed permanently.
    """
    try:
        for attempt in range(retries):
            try:
                response = session.get(url, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                return response.text
            except requests.exceptions.HTTPError as e:
                logger.warning(f"HTTP {response.status_code} for {url} — skipping.")
                return None
            except requests.exceptions.Timeout:
                logger.warning(f"Timeout on {url} (attempt {attempt + 1}/{retries})")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    logger.error(f"All {retries} attempts timed out for {url}")
                    return None
            except requests.exceptions.RequestException as e:
                logger.warning(f"Request error on {url} (attempt {attempt + 1}/{retries}): {e}")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    logger.error(f"Failed to fetch {url} after {retries} attempts: {e}")
                    return None
    except Exception as e:
        logger.error(f"Unexpected error fetching {url}: {e}")
        return None


def log_failed_url(url: str) -> None:
    """
    Append a failed URL to the failed_urls.txt file for later inspection.

    This function must never raise. Any failure to write is logged but
    silently swallowed so the scraper can continue uninterrupted.

    Args:
        url: The URL that failed to scrape successfully.
    """
    try:
        with open(FAILED_FILE, "a", encoding="utf-8") as f:
            f.write(url + "\n")
    except Exception as e:
        logger.error(f"Could not write to {FAILED_FILE}: {e}")


def fetch_letter_index(letter: str) -> Optional[str]:
    """
    Fetch the HTML of a letter index page from the Boericke Materia Medica.

    Constructs the URL from the letter and delegates to fetch_page.
    e.g. letter="A" → http://homeoint.org/books/boericmm/a.htm

    Args:
        letter: Single uppercase letter A–Z.

    Returns:
        Raw HTML string of the index page, or None if the fetch failed.
    """
    url = BASE_URL + letter.lower() + ".htm"
    logger.info(f"Fetching index for letter {letter}...")
    return fetch_page(url)


def parse_remedy_links(html: str, letter: str) -> List[Tuple[str, str]]:
    """
    Parse all remedy abbreviation+URL pairs from a letter index page.

    Extracts only remedy links from the <blockquote> section, skipping
    all navigation links (links to other letters or the main index).

    Args:
        html:   Raw HTML of the letter index page.
        letter: Uppercase letter this page belongs to (used for logging).

    Returns:
        List of (abbreviation, absolute_url) tuples, e.g.:
        [
            ("ABIES-C", "http://homeoint.org/books/boericmm/a/abies-c.htm"),
            ("ABIES-N", "http://homeoint.org/books/boericmm/a/abies-n.htm"),
            ...
        ]
        Returns an empty list if parsing fails or no links are found.
    """
    try:
        soup = BeautifulSoup(html, "lxml")
        blockquote = soup.find("blockquote")
        if not blockquote:
            logger.warning(f"No <blockquote> found on index page for letter {letter}")
            return []

        results = []
        seen_urls: Set[str] = set()
        for tag in blockquote.find_all("a"):
            if tag.find_parent("b"):
                continue
            href = tag.get("href", "").strip()
            if not href:
                continue
            text = tag.get_text(strip=True)
            if not text:
                continue
            if "index" in href:
                continue
            if re.search(r"/[a-z]\.htm$", href):
                continue

            abbreviation = text.upper()
            absolute_url = href if href.startswith("http") else urljoin(BASE_URL, href)
            if absolute_url in seen_urls:
                continue
            seen_urls.add(absolute_url)
            results.append((abbreviation, absolute_url))

        logger.info(f"Found {len(results)} remedies for letter {letter}")
        return results
    except Exception as e:
        logger.error(f"Failed to parse index for letter {letter}: {e}")
        return []


def clean_text(raw: str) -> str:
    """Strip HTML artifacts and normalise whitespace."""
    return re.sub(r'\s+', ' ', raw).strip()


def parse_remedy_page(
    html: str,
    url: str,
    abbreviation: str,
    letter: str,
) -> Optional[RemedyRecord]:
    """
    Parse a single remedy HTML page into a structured RemedyRecord.

    Handles all known structural variations in the Boericke Materia Medica
    pages including: remedies with and without common names, remedies with
    and without Relationship sections, and sections that run together without
    newline separators.

    The actual pages render content as flat <body> children after lxml parses
    the deeply-nested, malformed HTML from the site. Section headings appear
    in either <font> tags or <p><b> tags depending on the page.

    Args:
        html:         Raw HTML of the remedy page.
        url:          Source URL of this page (stored as-is in the record).
        abbreviation: Uppercase abbreviation from the index page e.g. "ABIES-C".
        letter:       Uppercase single letter e.g. "A".

    Returns:
        Fully populated RemedyRecord on success.
        None if a critical parsing failure occurs (logged before returning).
    """
    try:
        from bs4 import NavigableString as NS

        soup = BeautifulSoup(html, "lxml")
        body = soup.find("body")
        if not body:
            logger.warning(f"No <body> found for {url}")
            return None

        HEADING_RE = re.compile(r'^([A-Z][a-zA-Z\s\-\/]+)\.--\s*(.*)', re.DOTALL)
        # Matches the site header/footer paragraphs that should be skipped
        SKIP_RE = re.compile(r'BOERICKE|M\xe9di-T|Copyright|Presented by', re.IGNORECASE)

        full_name: Optional[str] = None
        common_name: Optional[str] = None
        general_parts: List[str] = []
        sections: Dict[str, str] = {}
        current_section: Optional[str] = None
        current_parts: List[str] = []
        in_general = True
        found_name = False

        def add_text(text: str) -> None:
            if not text:
                return
            if in_general:
                general_parts.append(text)
            elif current_section is not None:
                current_parts.append(text)

        for child in body.children:
            if isinstance(child, NS):
                if not found_name:
                    continue
                add_text(child.strip())

            elif hasattr(child, 'name'):
                tag_text = child.get_text(strip=True)

                if child.name == 'p':
                    if not tag_text or not tag_text.replace('\xa0', '').strip():
                        continue
                    if SKIP_RE.search(tag_text):
                        continue

                    if not found_name:
                        # First meaningful <p> after header is the remedy name
                        b_tag = child.find('b')
                        if b_tag:
                            font_tag = b_tag.find('font')
                            if font_tag:
                                full_name = clean_text(font_tag.get_text())
                                cn_parts = []
                                for sib in font_tag.next_siblings:
                                    if isinstance(sib, NS):
                                        s = sib.strip()
                                        if s:
                                            cn_parts.append(s)
                                common_name = clean_text(' '.join(cn_parts)) or None
                            else:
                                full_name = clean_text(b_tag.get_text())
                            found_name = True
                        continue

                    # After finding name: check if <p> is a section heading.
                    # Headings appear either as plain text ("Mind.--Great fear...")
                    # or wrapped in a <b> tag ("<b>Section.--</b>text...").
                    heading_match = HEADING_RE.match(tag_text)
                    b_tag = child.find('b')
                    b_heading_match = HEADING_RE.match(b_tag.get_text(strip=True)) if b_tag else None

                    if heading_match or b_heading_match:
                        m = heading_match or b_heading_match
                        if not in_general and current_section is not None:
                            sections[current_section] = clean_text(' '.join(current_parts))
                        in_general = False
                        current_section = m.group(1).strip()
                        if b_heading_match and b_tag:
                            # Collect text after the <b> inside this <p>
                            rest: List[str] = []
                            for sib in b_tag.next_siblings:
                                s = sib.strip() if isinstance(sib, NS) else (
                                    sib.get_text(strip=True) if hasattr(sib, 'get_text') else '')
                                if s:
                                    rest.append(s)
                            current_parts = [clean_text(' '.join(rest))] if rest else []
                        else:
                            # Plain-text heading: remainder is everything after "Heading.-- "
                            remainder = m.group(2).strip()
                            current_parts = [remainder] if remainder else []
                        continue

                    # Plain <p> — treat as content
                    add_text(tag_text)

                elif child.name == 'font':
                    if not found_name:
                        continue
                    m = HEADING_RE.match(tag_text)
                    if m:
                        if not in_general and current_section is not None:
                            sections[current_section] = clean_text(' '.join(current_parts))
                        in_general = False
                        current_section = m.group(1).strip()
                        remainder = m.group(2).strip()
                        current_parts = [remainder] if remainder else []
                    else:
                        add_text(tag_text)

                else:
                    if found_name:
                        add_text(tag_text)

        # Flush the last section
        if current_section is not None:
            sections[current_section] = clean_text(' '.join(current_parts))

        if not full_name:
            logger.warning(f"Could not find full_name for {url}")
            return None

        general = clean_text(' '.join(general_parts))

        # --- Extract relationships ---
        relationships: Optional[str] = None
        for key in ("Relationship", "Relationships"):
            if key in sections:
                relationships = sections[key]
                break

        return RemedyRecord(
            abbreviation=abbreviation,
            full_name=full_name,
            common_name=common_name,
            source_url=url,
            letter=letter,
            general=general,
            sections=sections,
            relationships=relationships,
            potencies=[],
            keywords=[],
        )

    except Exception as e:
        logger.error(f"Critical parse failure for {url}: {e}")
        return None


def extract_potencies(dose_text: str) -> List[str]:
    """
    Extract and normalise potency tokens from a remedy's Dose section text.

    Handles both numeric potencies (e.g. "30c", "6x") and named ordinal
    potencies (e.g. "third", "thirtieth"). Deduplicates while preserving
    the order of first appearance.

    Args:
        dose_text: Raw text of the Dose section. Empty string if no Dose
                   section exists for this remedy.

    Returns:
        Deduplicated list of normalised potency strings e.g. ["1c", "3c"].
        Empty list if no potencies found or dose_text is empty.
    """
    try:
        if not dose_text:
            return []

        results: List[str] = []
        lowered = dose_text.lower()

        # Step 1 — named potency scan (fixed order)
        for key in ("first", "second", "third", "sixth", "thirtieth",
                    "two-hundredth", "two hundredth"):
            if key in lowered:
                results.append(NAMED_POTENCIES[key])

        # Step 2 — numeric potency scan
        for match in re.findall(r'\b(\d+\s*[xXcC])\b', dose_text):
            results.append(re.sub(r'\s+', '', match).lower())

        # Step 3 — range expansion (e.g. "3-30c")
        for m in re.finditer(r'\b(\d+)-(\d+)\s*([xXcC])\b', dose_text):
            suffix = m.group(3).lower()
            results.append(f"{m.group(1)}{suffix}")
            results.append(f"{m.group(2)}{suffix}")

        # Step 4 — deduplicate, preserve order
        return list(dict.fromkeys(results))

    except Exception as e:
        logger.warning(f"extract_potencies failed: {e}")
        return []


def extract_keywords(record: RemedyRecord, top_n: int = 10) -> List[str]:
    """
    Extract the top N symptom keywords from a remedy's combined text content.

    Combines the general description and all section values, tokenises into
    words of 4+ characters, removes stopwords, and returns the most frequent
    terms. This gives a fast, lightweight keyword signal for each remedy
    without requiring external NLP libraries.

    Args:
        record: The RemedyRecord to analyse. Must have general and sections
                populated before this function is called.
        top_n:  Number of top keywords to return. Defaults to 10.

    Returns:
        List of up to top_n keyword strings ordered by frequency descending.
        Empty list if the combined text is too short to extract keywords.
    """
    try:
        parts = [record["general"]] + list(record["sections"].values())
        corpus = " ".join(parts).lower()

        if len(corpus) < 50:
            return []

        tokens = re.findall(r'\b[a-z]{4,}\b', corpus)
        filtered = [t for t in tokens if t not in STOPWORDS]
        counter = Counter(filtered)
        return [word for word, _ in counter.most_common(top_n)]

    except Exception as e:
        logger.warning(f"extract_keywords failed: {e}")
        return []


def upload_to_mongo(remedies: List[RemedyRecord], mongo_uri: str) -> None:
    """
    Upsert all remedy records into a MongoDB collection.

    Each remedy is upserted (inserted or updated) keyed on its source_url,
    so this function is safe to call multiple times — re-uploading will
    update existing records rather than creating duplicates.

    Targets database: "jarvis_care", collection: "remedies".

    Args:
        remedies:  Full list of RemedyRecord dicts to upload.
        mongo_uri: MongoDB connection string e.g. "mongodb://localhost:27017/".
    """
    client = None
    try:
        client = pymongo.MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
        client.server_info()
        collection = client["jarvis_care"]["remedies"]
        total = len(remedies)
        for i, remedy in enumerate(remedies, 1):
            collection.update_one(
                {"source_url": remedy["source_url"]},
                {"$set": remedy},
                upsert=True,
            )
            if i % 50 == 0 or i == total:
                logger.info(f"Uploaded {i}/{total} remedies to MongoDB")
        logger.info("MongoDB upload complete.")
    except pymongo.errors.ServerSelectionTimeoutError:
        logger.error(
            f"Could not connect to MongoDB at {mongo_uri}. "
            "Is the server running? Skipping upload."
        )
    except Exception as e:
        logger.error(f"MongoDB upload failed: {e}")
    finally:
        if client is not None:
            client.close()


def load_existing_output(path: str) -> Tuple[List[RemedyRecord], Set[str]]:
    """
    Load previously scraped remedies from disk to enable resumability.

    If the output file exists and is valid, returns all existing records
    and a set of their source URLs. The scraper uses the URL set to skip
    remedies that have already been scraped in a previous run.

    Args:
        path: Path to the output JSON file (e.g. "boericke_remedies.json").

    Returns:
        Tuple of (list of existing RemedyRecord dicts, set of source URLs).
        Returns ([], set()) if the file does not exist, is empty, or is
        invalid JSON — in all cases the scraper starts fresh.
    """
    if not os.path.exists(path):
        return [], set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if not content or content == "[]":
            return [], set()
        records: List[RemedyRecord] = json.loads(content)
        if not isinstance(records, list):
            logger.warning(f"Output file {path} does not contain a JSON array. Starting fresh.")
            return [], set()
        seen_urls: Set[str] = {
            r["source_url"] for r in records if "source_url" in r
        }
        logger.info(f"Loaded {len(records)} existing records from {path}.")
        return records, seen_urls
    except json.JSONDecodeError as e:
        logger.warning(f"Could not parse {path}: {e}. Starting fresh.")
        return [], set()
    except Exception as e:
        logger.warning(f"Could not load {path}: {e}. Starting fresh.")
        return [], set()


def save_output(remedies: List[RemedyRecord], path: str) -> None:
    """
    Atomically write the full list of remedies to a JSON file.

    Uses a write-to-temp-then-replace strategy to ensure the output file
    is never left in a corrupt or partial state, even if the process is
    killed mid-write.

    Args:
        remedies: Full list of RemedyRecord dicts scraped so far.
        path:     Destination file path e.g. "boericke_remedies.json".
    """
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(remedies, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
    except Exception as e:
        logger.error(f"Failed to save output to {path}: {e}")
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def main() -> None:
    """
    Entry point for the Boericke Materia Medica scraper.

    Parses CLI arguments, loads any existing output for resumability,
    crawls all specified letters, scrapes each remedy page, enriches
    records with potencies and keywords, and saves output incrementally.
    Optionally uploads the final dataset to MongoDB.
    """
    parser = argparse.ArgumentParser(
        description="Scrape Boericke's Homoeopathic Materia Medica into JSON.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scraper.py                          # scrape all A-Z
  python scraper.py --letters A,B,C         # scrape subset
  python scraper.py --upload                # scrape + upload to MongoDB
  python scraper.py --letters A --output test.json  # custom output path
    """,
    )
    parser.add_argument(
        "--letters",
        type=str,
        default=",".join(LETTERS),
        help="Comma-separated letters to scrape (default: A-Z)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=OUTPUT_FILE,
        help=f"Output JSON file path (default: {OUTPUT_FILE})",
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Upload scraped data to MongoDB after scraping",
    )
    parser.add_argument(
        "--mongo-uri",
        type=str,
        default="mongodb://localhost:27017/",
        help="MongoDB connection URI (default: mongodb://localhost:27017/)",
    )
    parser.add_argument(
        "--delay-min",
        type=float,
        default=DELAY_MIN,
        help=f"Minimum delay between requests in seconds (default: {DELAY_MIN})",
    )
    parser.add_argument(
        "--delay-max",
        type=float,
        default=DELAY_MAX,
        help=f"Maximum delay between requests in seconds (default: {DELAY_MAX})",
    )
    args = parser.parse_args()

    letters_to_scrape = [l.strip().upper() for l in args.letters.split(",")]
    invalid = [l for l in letters_to_scrape if l not in LETTERS]
    if invalid:
        parser.error(f"Invalid letters: {invalid}. Must be A-Z.")

    logger.info("=" * 60)
    logger.info("Boericke Materia Medica Scraper — jarvis.care")
    logger.info(f"Letters : {', '.join(letters_to_scrape)}")
    logger.info(f"Output  : {args.output}")
    logger.info(f"Upload  : {args.upload}")
    logger.info("=" * 60)

    remedies, seen_urls = load_existing_output(args.output)
    logger.info(f"Resuming with {len(seen_urls)} already-scraped remedies.")

    for letter in letters_to_scrape:
        html = fetch_letter_index(letter)
        if html is None:
            logger.warning(f"[{letter}] Could not fetch index page. Skipping letter.")
            continue

        links = parse_remedy_links(html, letter)
        if not links:
            logger.warning(f"[{letter}] No remedy links found. Skipping letter.")
            continue

        total = len(links)
        logger.info(f"[{letter}] Found {total} remedies to scrape.")

        for i, (abbrev, url) in enumerate(links, 1):
            if url in seen_urls:
                logger.info(f"[{letter}] Skipping {abbrev} (already scraped).")
                continue

            html = fetch_page(url)
            if html is None:
                logger.warning(f"[{letter}] Failed to fetch {abbrev} — logging and continuing.")
                log_failed_url(url)
                continue

            record = parse_remedy_page(html, url, abbrev, letter)
            if record is None:
                logger.warning(f"[{letter}] Failed to parse {abbrev} — logging and continuing.")
                log_failed_url(url)
                continue

            record["potencies"] = extract_potencies(
                record["sections"].get("Dose", "")
            )
            record["keywords"] = extract_keywords(record)

            remedies.append(record)
            seen_urls.add(url)
            save_output(remedies, args.output)

            print(f"[{letter}] Scraped {i}/{total} - {record['full_name']}")

            time.sleep(random.uniform(args.delay_min, args.delay_max))

        logger.info(f"[{letter}] Finished. Total remedies so far: {len(remedies)}")

    logger.info("=" * 60)
    logger.info(f"Scraping complete. Total remedies scraped: {len(remedies)}")
    logger.info(f"Output saved to: {args.output}")

    if args.upload:
        logger.info("Uploading to MongoDB...")
        upload_to_mongo(remedies, args.mongo_uri)

    logger.info("Done.")


if __name__ == "__main__":
    main()
