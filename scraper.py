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
