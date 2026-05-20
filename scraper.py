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
