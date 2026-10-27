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
from src.curation import same_item


def article(title="Model update", url="https://openai.com/index/update", **kwargs):
    return Article(title=title, url=url, hn_url="", score=kwargs.pop("score", 0), comment_count=kwargs.pop("comment_count", 0), **kwargs)


class LLMDigestTests(unittest.TestCase):
    def test_hot_ranking_prefers_engagement_over_newness(self):
        hot = article(title="DeepSeek reasoning breakthrough", score=500, comment_count=120, source="news.example.org")
        newer = article(title="Introducing Claude API", url="https://anthropic.com/news/new", source="Anthropic", source_type="official")
        results = llm.rank_hot_candidates([(900, "DeepSeek", hot), (999, "Anthropic", newer)], 1000, 5)
        self.assertEqual(results, [hot, newer])

    def test_low_interest_items_do_not_fill_five_slots(self):
        quiet = article(title="15 students share Gemini tips", source="Google", source_type="official")
        launch = article(title="Introducing GPT-6 Astra", url="https://openai.com/index/astra", source="OpenAI", source_type="official")
        results = llm.rank_hot_candidates([(999, "Gemini", quiet), (900, "OpenAI", launch)], 1000, 5)
        self.assertEqual(results, [launch])

    def test_multiple_search_hits_from_one_publisher_are_not_corroboration(self):
        first = article(title="Claude API pricing announced", url="https://reuters.com/new", source="Reuters")
        second = article(title=first.title, url="https://news.google.com/rss/articles/new", source="reuters.com")
        self.assertEqual(llm.rank_hot_candidates([(990, "Anthropic", first), (991, "Anthropic", second)], 1000, 5), [])

    def test_corroborated_impact_becomes_one_item_with_original_link(self):
        original = article(title="Introducing GPT-6 Astra", source="OpenAI", source_type="official")
        coverage = article(title=original.title, url="https://techcrunch.com/news/astra", source="TechCrunch", score=120)
        results = llm.rank_hot_candidates([(990, "OpenAI", original), (995, "OpenAI", coverage)], 1000, 5)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, original.url)
        self.assertEqual(results[0].score, 120)

    def test_llm_section_is_capped_at_five(self):
        candidates = [(900 + i, "OpenAI", article(title=f"Introducing GPT-{i + 10}", url=f"https://openai.com/index/model-{i}", source="OpenAI", source_type="official")) for i in range(8)]
        with patch.object(llm, "_feed_candidates", return_value=candidates), patch.object(llm, "_hn_candidates", return_value=[]):
            self.assertEqual(len(llm.fetch_llm_articles(count=20)), 5)

    def test_different_model_versions_are_distinct_items(self):
        self.assertFalse(same_item(article(title="Introducing GPT-6.1 Terra", url="https://example.org/one"), article(title="Introducing GPT-6.2 Terra", url="https://example.org/two")))

    def test_identifiable_hot_event_is_one_topic_across_publishers(self):
        first = article(title="Anthropic IPO filing reveals revenues", url="https://example.org/one", source="Reuters")
        second = article(title="AI chip stocks rally after Anthropic IPO", url="https://example.org/two", source="Bloomberg")
        self.assertTrue(same_item(first, second))
        results = llm.rank_hot_candidates([(990, "Anthropic", first), (995, "Anthropic", second)], 1000, 5)
        self.assertEqual(len(results), 1)

    def test_same_headline_in_tech_and_llm_is_displayed_once(self):
        update = article(title="OpenAI releases GPT-6 Astra", section="llm")
        repeat = article(title=update.title + " - Reuters", url="https://reuters.com/news/astra")
        other = article(title="Linux kernel update", url="https://example.org/linux")
        with patch.object(tech, "fetch_llm_articles", return_value=[update]), patch.object(tech, "_fetch_hn_articles", return_value=[repeat, other]):
            self.assertEqual(tech.fetch_tech_articles(), [other, update])

    def test_separate_emails_do_not_use_past_delivery_history(self):
        server = Mock()
        subscriber = Subscriber("reader@example.org", Language.EN)
        for _ in range(2):
            send_email_to_subscriber([article(section="llm")], subscriber, topic=Topic.TECH, smtp_server=server)
        self.assertEqual(server.send_message.call_count, 2)

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
