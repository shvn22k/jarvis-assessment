"""
Test suite for the Boericke Homoeopathic Materia Medica Scraper.

Structure:
  - Unit tests: pure logic, no network, run instantly
  - Integration tests: real HTTP requests, marked with @integration
    Skip integration tests in CI by running:
      python -m unittest discover -k "not Integration"

Usage:
  Run all tests:           python -m unittest tests/test_scraper.py -v
  Run unit tests only:     python -m unittest tests/test_scraper.py -v -k "Unit"
  Run integration tests:   python -m unittest tests/test_scraper.py -v -k "Integration"
"""

import json
import os
import sys
import unittest

# Ensure scraper.py is importable from the project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper import (
    BASE_URL,
    RemedyRecord,
    STOPWORDS,
    clean_text,
    extract_keywords,
    extract_potencies,
    fetch_letter_index,
    fetch_page,
    load_existing_output,
    log_failed_url,
    parse_remedy_links,
    parse_remedy_page,
    save_output,
)

# ---------------------------------------------------------------------------
# Integration test decorator
# ---------------------------------------------------------------------------

SKIP_INTEGRATION = os.environ.get("SKIP_INTEGRATION", "").lower() in ("1", "true", "yes")


def integration(cls_or_func):
    """
    Marks a test class or method as requiring network access.
    Set SKIP_INTEGRATION=1 to skip all integration tests.
    """
    decorator = unittest.skipIf(
        SKIP_INTEGRATION,
        "Integration tests skipped (SKIP_INTEGRATION=1)"
    )
    return decorator(cls_or_func)


# ---------------------------------------------------------------------------
# Test Class 1 — TestCleanText (Unit)
# ---------------------------------------------------------------------------

class TestCleanText(unittest.TestCase):
    """Unit tests for the clean_text helper function."""

    def test_collapses_multiple_spaces(self):
        self.assertEqual(clean_text("hello   world"), "hello world")

    def test_strips_leading_trailing_whitespace(self):
        self.assertEqual(clean_text("  hello  "), "hello")

    def test_collapses_newlines_and_tabs(self):
        self.assertEqual(clean_text("hello\n\t\r\nworld"), "hello world")

    def test_empty_string(self):
        self.assertEqual(clean_text(""), "")

    def test_preserves_punctuation(self):
        result = clean_text("burning, pain. with (anxiety)")
        self.assertEqual(result, "burning, pain. with (anxiety)")

    def test_already_clean_string_unchanged(self):
        text = "This is a clean string."
        self.assertEqual(clean_text(text), text)


# ---------------------------------------------------------------------------
# Test Class 2 — TestExtractPotencies (Unit)
# ---------------------------------------------------------------------------

class TestExtractPotencies(unittest.TestCase):
    """Unit tests for potency extraction from Dose section text."""

    def test_named_ordinals_first_to_third(self):
        result = extract_potencies("First to third potency.")
        self.assertEqual(result, ["1c", "3c"])

    def test_named_ordinals_sixth_to_thirtieth(self):
        result = extract_potencies("Sixth to thirtieth potency.")
        self.assertEqual(result, ["6c", "30c"])

    def test_numeric_tokens(self):
        result = extract_potencies("Use 6x or 30c.")
        self.assertIn("6x", result)
        self.assertIn("30c", result)

    def test_range_expansion(self):
        result = extract_potencies("Third to thirtieth potency.")
        self.assertIn("3c", result)
        self.assertIn("30c", result)

    def test_deduplication(self):
        result = extract_potencies("Third potency. Use 3c daily.")
        self.assertEqual(result.count("3c"), 1)

    def test_empty_string_returns_empty_list(self):
        self.assertEqual(extract_potencies(""), [])

    def test_no_potency_info_returns_empty_list(self):
        self.assertEqual(extract_potencies("No potency info here."), [])

    def test_returns_list_type(self):
        result = extract_potencies("Third potency.")
        self.assertIsInstance(result, list)

    def test_all_tokens_are_lowercase_strings(self):
        result = extract_potencies("Use 6X or 30C potency.")
        for token in result:
            self.assertIsInstance(token, str)
            self.assertEqual(token, token.lower())


# ---------------------------------------------------------------------------
# Test Class 3 — TestExtractKeywords (Unit)
# ---------------------------------------------------------------------------

class TestExtractKeywords(unittest.TestCase):
    """Unit tests for keyword extraction from remedy text."""

    def _make_record(self, general: str, sections: dict) -> RemedyRecord:
        """Helper to build a minimal RemedyRecord for testing."""
        return RemedyRecord(
            abbreviation="TEST",
            full_name="TEST REMEDY",
            common_name=None,
            source_url="http://example.com/test",
            letter="T",
            general=general,
            sections=sections,
            relationships=None,
            potencies=[],
            keywords=[],
        )

    def test_returns_list(self):
        record = self._make_record("burning pain restlessness anxiety", {})
        self.assertIsInstance(extract_keywords(record), list)

    def test_respects_top_n(self):
        record = self._make_record(
            "burning pain restlessness anxiety tingling coldness",
            {"Head": "throbbing headache burning sensation vertigo"},
        )
        result = extract_keywords(record, top_n=3)
        self.assertLessEqual(len(result), 3)

    def test_no_stopword_leaks(self):
        record = self._make_record(
            "burning pain with restlessness and anxiety",
            {"Head": "throbbing headache burning sensation"},
        )
        result = extract_keywords(record)
        for word in result:
            self.assertNotIn(word, STOPWORDS)

    def test_no_short_word_leaks(self):
        record = self._make_record(
            "burning pain with restlessness and anxiety",
            {},
        )
        result = extract_keywords(record)
        for word in result:
            self.assertGreaterEqual(len(word), 4)

    def test_short_text_returns_empty(self):
        record = self._make_record("hi", {})
        self.assertEqual(extract_keywords(record), [])

    def test_frequent_word_ranked_first(self):
        record = self._make_record(
            "burning burning burning pain restlessness",
            {"Head": "burning sensation"},
        )
        result = extract_keywords(record)
        self.assertEqual(result[0], "burning")


# ---------------------------------------------------------------------------
# Test Class 4 — TestParseRemedyLinks (Unit)
# ---------------------------------------------------------------------------

class TestParseRemedyLinks(unittest.TestCase):
    """Unit tests for remedy link parsing from letter index HTML."""

    # Minimal HTML that mimics the real blockquote structure
    SAMPLE_HTML = """
    <html><body><blockquote>
      <b>
        <a href="http://homeoint.org/books/boericmm/index.htm">MAIN</a> *
        <a href="http://homeoint.org/books/boericmm/b.htm">B</a>
      </b>
      <a href="a/abies-c.htm">Abies-c</a> *
      <a href="a/acon.htm">Acon</a> *
      <a href="a/ars.htm">Ars</a>
    </blockquote></body></html>
    """

    def test_returns_correct_count(self):
        links = parse_remedy_links(self.SAMPLE_HTML, "A")
        self.assertEqual(len(links), 3)

    def test_abbreviations_are_uppercase(self):
        links = parse_remedy_links(self.SAMPLE_HTML, "A")
        for abbrev, _ in links:
            self.assertEqual(abbrev, abbrev.upper())

    def test_urls_are_absolute(self):
        links = parse_remedy_links(self.SAMPLE_HTML, "A")
        for _, url in links:
            self.assertTrue(url.startswith("http"))

    def test_nav_links_excluded(self):
        links = parse_remedy_links(self.SAMPLE_HTML, "A")
        urls = [u for _, u in links]
        self.assertNotIn("http://homeoint.org/books/boericmm/index.htm", urls)
        for url in urls:
            self.assertNotIn("index", url)

    def test_known_abbreviations_present(self):
        links = parse_remedy_links(self.SAMPLE_HTML, "A")
        abbrevs = [a for a, _ in links]
        self.assertIn("ABIES-C", abbrevs)
        self.assertIn("ACON", abbrevs)
        self.assertIn("ARS", abbrevs)

    def test_empty_html_returns_empty_list(self):
        result = parse_remedy_links("<html><body></body></html>", "A")
        self.assertEqual(result, [])

    def test_no_duplicate_urls(self):
        # Simulate the duplicate structure found on the real site
        html = """
        <html><body><blockquote>
          <a href="a/abies-c.htm">Abies-c</a>
          <a href="a/abies-c.htm">Abies-c</a>
        </blockquote></body></html>
        """
        links = parse_remedy_links(html, "A")
        urls = [u for _, u in links]
        self.assertEqual(len(urls), len(set(urls)))


# ---------------------------------------------------------------------------
# Test Class 5 — TestSaveAndLoadOutput (Unit)
# ---------------------------------------------------------------------------

class TestSaveAndLoadOutput(unittest.TestCase):
    """Unit tests for output file save/load round-trip."""

    TEST_PATH = "tests/test_output_temp.json"

    def _make_record(self) -> RemedyRecord:
        return RemedyRecord(
            abbreviation="TEST",
            full_name="TEST REMEDY",
            common_name="Test Plant",
            source_url="http://homeoint.org/books/boericmm/t/test.htm",
            letter="T",
            general="A test remedy with burning pains.",
            sections={"Head": "Headache.", "Dose": "Third potency."},
            relationships="Compare: Acon.",
            potencies=["3c"],
            keywords=["burning", "headache"],
        )

    def tearDown(self):
        """Clean up temp file after each test."""
        if os.path.exists(self.TEST_PATH):
            os.remove(self.TEST_PATH)

    def test_save_creates_valid_json_file(self):
        save_output([self._make_record()], self.TEST_PATH)
        self.assertTrue(os.path.exists(self.TEST_PATH))
        with open(self.TEST_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_load_returns_correct_count(self):
        save_output([self._make_record()], self.TEST_PATH)
        records, seen_urls = load_existing_output(self.TEST_PATH)
        self.assertEqual(len(records), 1)

    def test_load_returns_correct_seen_urls(self):
        record = self._make_record()
        save_output([record], self.TEST_PATH)
        _, seen_urls = load_existing_output(self.TEST_PATH)
        self.assertIn(record["source_url"], seen_urls)

    def test_round_trip_preserves_all_fields(self):
        record = self._make_record()
        save_output([record], self.TEST_PATH)
        loaded, _ = load_existing_output(self.TEST_PATH)
        for field in record:
            self.assertEqual(loaded[0][field], record[field])

    def test_load_missing_file_returns_empty(self):
        records, seen_urls = load_existing_output("nonexistent_file.json")
        self.assertEqual(records, [])
        self.assertEqual(seen_urls, set())

    def test_load_empty_file_returns_empty(self):
        save_output([], self.TEST_PATH)
        records, seen_urls = load_existing_output(self.TEST_PATH)
        self.assertEqual(records, [])
        self.assertEqual(seen_urls, set())

    def test_atomic_write_no_tmp_file_left_on_success(self):
        save_output([self._make_record()], self.TEST_PATH)
        self.assertFalse(os.path.exists(self.TEST_PATH + ".tmp"))


# ---------------------------------------------------------------------------
# Test Class 6 — TestLogFailedUrl (Unit)
# ---------------------------------------------------------------------------

class TestLogFailedUrl(unittest.TestCase):
    """Unit tests for failed URL logging."""

    TEST_FAILED_PATH = "tests/test_failed_temp.txt"

    def setUp(self):
        import scraper
        self._original = scraper.FAILED_FILE
        scraper.FAILED_FILE = self.TEST_FAILED_PATH

    def tearDown(self):
        import scraper
        scraper.FAILED_FILE = self._original
        if os.path.exists(self.TEST_FAILED_PATH):
            os.remove(self.TEST_FAILED_PATH)

    def test_writes_url_to_file(self):
        log_failed_url("http://example.com/test")
        with open(self.TEST_FAILED_PATH, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        self.assertIn("http://example.com/test", lines)

    def test_appends_multiple_urls(self):
        log_failed_url("http://example.com/one")
        log_failed_url("http://example.com/two")
        with open(self.TEST_FAILED_PATH, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        self.assertIn("http://example.com/one", lines)
        self.assertIn("http://example.com/two", lines)
        self.assertEqual(len(lines), 2)

    def test_never_raises(self):
        """log_failed_url must never raise even with an invalid path."""
        import scraper
        scraper.FAILED_FILE = "/invalid/path/that/does/not/exist.txt"
        try:
            log_failed_url("http://example.com/test")
        except Exception as e:
            self.fail(f"log_failed_url raised an exception: {e}")


# ---------------------------------------------------------------------------
# Test Class 7 — TestFetchPageIntegration (Integration)
# ---------------------------------------------------------------------------

@integration
class TestFetchPageIntegration(unittest.TestCase):
    """Integration tests for the HTTP fetch layer. Requires network access."""

    REAL_URL = "http://homeoint.org/books/boericmm/a/abies-c.htm"
    BAD_URL = "http://homeoint.org/books/boericmm/DOESNOTEXIST_404.htm"

    def test_fetches_real_page_successfully(self):
        html = fetch_page(self.REAL_URL)
        self.assertIsNotNone(html)
        self.assertIn("ABIES", html)

    def test_returns_none_for_404(self):
        result = fetch_page(self.BAD_URL)
        self.assertIsNone(result)

    def test_returns_string_on_success(self):
        html = fetch_page(self.REAL_URL)
        self.assertIsInstance(html, str)
        self.assertGreater(len(html), 100)


# ---------------------------------------------------------------------------
# Test Class 8 — TestParseRemedyPageIntegration (Integration)
# ---------------------------------------------------------------------------

@integration
class TestParseRemedyPageIntegration(unittest.TestCase):
    """
    Integration tests for parse_remedy_page against real live pages.
    Tests all four structural variants documented during Phase 4.
    """

    def _scrape(self, url: str, abbrev: str, letter: str) -> RemedyRecord:
        html = fetch_page(url)
        self.assertIsNotNone(html, f"Could not fetch {url}")
        record = parse_remedy_page(html, url, abbrev, letter)
        self.assertIsNotNone(record, f"parse_remedy_page returned None for {url}")
        return record

    def test_abies_c_standard_structure(self):
        r = self._scrape(
            "http://homeoint.org/books/boericmm/a/abies-c.htm", "ABIES-C", "A"
        )
        self.assertEqual(r["full_name"], "ABIES CANADENSIS-PINUS CANADENSIS")
        self.assertEqual(r["common_name"], "Hemlock Spruce")
        self.assertIsNone(r["relationships"])
        for section in ["Head", "Stomach", "Female", "Fever", "Dose"]:
            self.assertIn(section, r["sections"])
        self.assertGreater(len(r["general"]), 30)

    def test_acon_with_relationship_section(self):
        r = self._scrape(
            "http://homeoint.org/books/boericmm/a/acon.htm", "ACON", "A"
        )
        self.assertEqual(r["full_name"], "ACONITUM NAPELLUS")
        self.assertEqual(r["common_name"], "Monkshood")
        self.assertIsNotNone(r["relationships"])
        self.assertIn("Mind", r["sections"])
        self.assertIn("Dose", r["sections"])

    def test_adren_multiline_common_name(self):
        r = self._scrape(
            "http://homeoint.org/books/boericmm/a/adren.htm", "ADREN", "A"
        )
        self.assertEqual(r["full_name"], "ADRENALINUM")
        self.assertIsNotNone(r["common_name"])
        self.assertIn("ADRENALIN", r["common_name"].upper())
        self.assertIn("Uses", r["sections"])

    def test_acal_sections_run_together(self):
        r = self._scrape(
            "http://homeoint.org/books/boericmm/a/acal.htm", "ACAL", "A"
        )
        self.assertEqual(r["full_name"], "ACALYPHA INDICA")
        self.assertEqual(r["common_name"], "Indian Nettle")
        for section in ["Chest", "Abdomen", "Skin", "Dose"]:
            self.assertIn(section, r["sections"])

    def test_all_required_fields_present(self):
        r = self._scrape(
            "http://homeoint.org/books/boericmm/a/ars.htm", "ARS", "A"
        )
        required = [
            "abbreviation", "full_name", "common_name", "source_url",
            "letter", "general", "sections", "relationships",
            "potencies", "keywords",
        ]
        for field in required:
            self.assertIn(field, r)

    def test_sections_is_never_none(self):
        r = self._scrape(
            "http://homeoint.org/books/boericmm/a/acon.htm", "ACON", "A"
        )
        self.assertIsInstance(r["sections"], dict)

    def test_general_text_is_non_empty(self):
        r = self._scrape(
            "http://homeoint.org/books/boericmm/a/acon.htm", "ACON", "A"
        )
        self.assertGreater(len(r["general"]), 50)


# ---------------------------------------------------------------------------
# Test Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
