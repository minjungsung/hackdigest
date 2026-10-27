"""Verify source selection and delivery of the combined Tech digest offline."""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from src import cache
from src.fetchers import llm, tech
from src.models import Article, Language, Subscriber, Topic
from src.notifier import send_email_to_subscriber
from src.summarizer import summarize


def article(title="Model update", url="https://openai.com/index/update", **kwargs):
    return Article(title=title, url=url, hn_url="", score=0, comment_count=0, **kwargs)


class LLMDigestTests(unittest.TestCase):
    def test_feed_excludes_old_future_undated_and_untrusted_entries(self):
        response = Mock(content=b"feed")
        entries = [
            {"title": "New GPT model", "link": "https://openai.com/index/new", "published_parsed": (2026, 10, 27, 1, 0, 0, 0, 0, 0)},
            {"title": "Old GPT model", "link": "https://openai.com/index/old", "published_parsed": (2026, 10, 25, 1, 0, 0, 0, 0, 0)},
            {"title": "Future GPT model", "link": "https://openai.com/index/future", "published_parsed": (2026, 10, 29, 1, 0, 0, 0, 0, 0)},
            {"title": "Undated GPT model", "link": "https://openai.com/index/undated"},
            {"title": "Fake GPT model", "link": "https://openai.com.evil.example/new", "published_parsed": (2026, 10, 27, 1, 0, 0, 0, 0, 0)},
        ]
        now = datetime(2026, 10, 27, 9, tzinfo=timezone.utc).timestamp()
        with patch.object(llm.requests, "get", return_value=response), patch.object(llm.feedparser, "parse", return_value=Mock(entries=entries)):
            results = llm._feed_candidates("OpenAI", "official", "https://example.org/feed", now - 86400, now)
        self.assertEqual([r[2].title for r in results], ["New GPT model"])

    def test_selection_deduplicates_and_limits_company_share(self):
        candidates = [(10 - i, "OpenAI", article(url=f"https://openai.com/index/{i}", section="llm", source_type="official")) for i in range(4)]
        candidates += [(6, "Anthropic", article(url="https://anthropic.com/news/new", section="llm"))]
        duplicate = (11, "OpenAI", article(url="https://openai.com/index/0/?utm_source=hn", section="llm", source_type="reporting"))
        with patch.object(llm, "_feed_candidates", side_effect=lambda *args: candidates if args[0] == "OpenAI" else []), patch.object(llm, "_hn_candidates", return_value=[duplicate]):
            results = llm.fetch_llm_articles()
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0].source_type, "official")
        self.assertEqual(sum("openai.com" in a.url for a in results), 2)

    def test_url_deduplication_preserves_distinct_videos(self):
        self.assertNotEqual(llm.canonical_url("https://youtube.com/watch?v=one"), llm.canonical_url("https://youtube.com/watch?v=two"))

    def test_hn_search_rejects_unrelated_results(self):
        response = Mock()
        response.json.return_value = {"hits": [
            {"title": "Fashion model reviews", "url": "https://example.org/fashion", "created_at_i": 100, "objectID": "1"},
            {"title": "Anthropic Claude model update", "url": "https://anthropic.com/news/update", "created_at_i": 100, "objectID": "2"},
        ]}
        with patch.object(llm.requests, "get", return_value=response):
            results = llm._hn_candidates("Anthropic", 0, 200)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][2].source_type, "official")

    def test_source_failures_do_not_block_other_sources(self):
        with patch.object(llm.requests, "get", side_effect=llm.requests.Timeout("offline")):
            self.assertEqual(llm._feed_candidates("OpenAI", "official", "https://example.org/feed", 0, 1), [])
            self.assertEqual(llm._hn_candidates("Anthropic", 0, 1), [])
        update = article(section="llm")
        with patch.object(tech, "fetch_llm_articles", return_value=[update]), patch.object(tech, "_fetch_hn_articles", side_effect=llm.requests.Timeout("offline")):
            self.assertEqual(tech.fetch_tech_articles(), [update])

    def test_one_tech_email_contains_both_sections_and_escaped_sources(self):
        update = article(title="LLM update", section="llm", source="Researcher <name>", source_type="analysis")
        hn = article(title="General tech", url="https://example.org/tech")
        duplicate = article(title="Duplicate", url=update.url + "?utm_source=hn")
        with patch.object(tech, "fetch_llm_articles", return_value=[update]), patch.object(tech, "_fetch_hn_articles", return_value=[duplicate, hn]):
            articles = tech.fetch_tech_articles()
        server = Mock()
        send_email_to_subscriber(articles, Subscriber("reader@example.org", Language.EN), topic=Topic.TECH, smtp_server=server)
        server.send_message.assert_called_once()
        message = server.send_message.call_args.args[0]
        body = message.get_payload()[0].get_payload(decode=True).decode()
        for text in ("General tech", "LLM update", "LLM companies & research", "Research commentary", "Researcher &lt;name&gt;"):
            self.assertIn(text, body)
        self.assertNotIn("Duplicate", body)

    def test_cache_round_trip_preserves_sources_and_reads_legacy_articles(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(cache, "CACHE_DIR", Path(directory)):
            original = article(section="llm", source="OpenAI", source_type="official")
            cache.save_articles([original], Topic.TECH)
            self.assertEqual(cache.load_articles(Topic.TECH), [original])
            path = cache._articles_filename(Topic.TECH, cache._today_kst())
            data = json.loads(path.read_text())
            for key in ("section", "source", "source_type"):
                del data[0][key]
            path.write_text(json.dumps(data))
            self.assertEqual(cache.load_articles(Topic.TECH)[0].source, "")

    def test_missing_llm_body_does_not_invent_details_from_title(self):
        update = article(section="llm")
        with patch("src.summarizer._translate_title", side_effect=lambda title, language: title), patch("src.summarizer._extract_body", return_value=""), patch("src.summarizer._summarize_from_title") as explain:
            summarize(update, language=Language.EN)
        explain.assert_not_called()
        self.assertIn("read the original", update.summary)

    def test_test_mode_without_recipient_refuses_delivery(self):
        from src.main import main
        with patch.dict("os.environ", {"HACKDIGEST_TEST_MODE": "true", "EMAIL_TEST_TO": ""}), patch("src.main.load_subscribers", return_value=[Subscriber("reader@example.org")]), patch("src.main.fetch_articles_by_topic") as fetch:
            with self.assertRaises(SystemExit) as error:
                main()
        self.assertEqual(error.exception.code, 1)
        fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
