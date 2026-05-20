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
