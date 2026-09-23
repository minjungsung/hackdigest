"""Cache module for saving/loading articles and summaries as JSON files."""

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.models import Article, Language, Topic

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
CACHE_DIR = Path("data/cache")


def _ensure_cache_dir() -> None:
    """Create data/cache/ directory if it doesn't exist."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _today_kst() -> str:
    """Return today's date string in YYYY-MM-DD format (KST)."""
    return datetime.now(KST).strftime("%Y-%m-%d")


def _articles_filename(topic: Topic, date: str) -> Path:
    """Return cache file path for articles: articles_YYYY-MM-DD_TOPIC.json"""
    return CACHE_DIR / f"articles_{date}_{topic.value}.json"


def _summaries_filename(language: Language, date: str) -> Path:
    """Return cache file path for summaries: summaries_YYYY-MM-DD_LANG.json"""
    return CACHE_DIR / f"summaries_{date}_{language.value}.json"


def save_articles(articles: list[Article], topic: Topic) -> None:
    """Save article data to a JSON cache file.

    Args:
        articles: List of Article objects to cache.
        topic: Topic category for the articles.
    """
    _ensure_cache_dir()
    date = _today_kst()
    filepath = _articles_filename(topic, date)

    data = [
        {
            "title": a.title,
            "url": a.url,
            "hn_url": a.hn_url,
            "score": a.score,
            "comment_count": a.comment_count,
            "topic": a.topic.value,
        }
        for a in articles
    ]

    filepath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Saved %d articles to %s", len(articles), filepath)


def load_articles(topic: Topic, date: str | None = None) -> list[Article]:
    """Load cached articles from a JSON file.

    Args:
        topic: Topic category to load.
        date: Date string (YYYY-MM-DD). Defaults to today (KST).

    Returns:
        List of Article objects, or empty list if cache miss.
    """
    if date is None:
        date = _today_kst()

    filepath = _articles_filename(topic, date)
    if not filepath.exists():
        logger.info("No article cache found at %s", filepath)
        return []

    data = json.loads(filepath.read_text(encoding="utf-8"))
    articles = [
        Article(
            title=item["title"],
            url=item["url"],
            hn_url=item["hn_url"],
            score=item["score"],
            comment_count=item["comment_count"],
            topic=Topic(item["topic"]),
        )
        for item in data
    ]
    logger.info("Loaded %d articles from %s", len(articles), filepath)
    return articles


def save_summaries(articles: list[Article], language: Language) -> None:
    """Save article summaries to a JSON cache file, keyed by URL.

    Args:
        articles: List of Article objects with summaries.
        language: Language of the summaries.
    """
    _ensure_cache_dir()
    date = _today_kst()
    filepath = _summaries_filename(language, date)

    data = {
        a.url: {
            "title": a.title,
            "summary": a.summary,
            "language": language.value,
        }
        for a in articles
        if a.summary
    }

    filepath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Saved %d summaries (%s) to %s", len(data), language.value, filepath)


def load_summaries(language: Language, date: str | None = None) -> dict[str, dict]:
    """Load cached summaries from a JSON file.

    Args:
        language: Language of summaries to load.
        date: Date string (YYYY-MM-DD). Defaults to today (KST).

    Returns:
        Dict mapping URL to summary data, or empty dict if cache miss.
    """
    if date is None:
        date = _today_kst()

    filepath = _summaries_filename(language, date)
    if not filepath.exists():
        logger.info("No summary cache found at %s", filepath)
        return {}

    data = json.loads(filepath.read_text(encoding="utf-8"))
    logger.info("Loaded %d summaries (%s) from %s", len(data), language.value, filepath)
    return data


def has_cache(date: str | None = None) -> bool:
    """Check if any cache files exist for the given date.

    Args:
        date: Date string (YYYY-MM-DD). Defaults to today (KST).

    Returns:
        True if at least one cache file exists for the date.
    """
    if date is None:
        date = _today_kst()

    if not CACHE_DIR.exists():
        return False

    pattern = f"*_{date}_*"
    return any(CACHE_DIR.glob(pattern))
