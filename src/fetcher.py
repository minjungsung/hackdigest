"""Fetch top stories from Hacker News API."""

import logging
import re
import time

import requests

from src.models import Article, Topic

logger = logging.getLogger(__name__)

HN_API_BASE = "https://hacker-news.firebaseio.com/v0"
REQUEST_TIMEOUT = 10
MAX_RETRIES = 3
PREFETCH_COUNT = 50  # Fetch more to have room after filtering

# Non-tech topics to exclude (case-insensitive)
NON_TECH_PATTERNS = re.compile(
    r"\b("
    r"politics|election|president|congress|senate|democrat|republican|biden|trump|"
    r"supreme court|abortion|immigration|gun control|"
    r"nfl|nba|mlb|fifa|olympics|world cup|"
    r"weight loss|diet pill|supplement|horoscope|astrology|"
    r"celebrity|kardashian|royal family|"
    r"recipe|cookbook|gardening"
    r")\b",
    re.IGNORECASE,
)


def _is_tech_related(title: str) -> bool:
    """Return True if the story appears to be tech/IT related (not excluded)."""
    return not NON_TECH_PATTERNS.search(title)


def _get_with_retry(url: str, retries: int = MAX_RETRIES) -> dict | list:
    """GET request with retry logic."""
    for attempt in range(retries):
        try:
            resp = requests.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.warning("Request failed (attempt %d/%d): %s", attempt + 1, retries, e)
            if attempt < retries - 1:
                time.sleep(1)
            else:
                raise


def _fetch_item(item_id: int) -> dict | None:
    """Fetch a single HN item. Returns None on failure."""
    try:
        return _get_with_retry(f"{HN_API_BASE}/item/{item_id}.json", retries=1)
    except requests.RequestException:
        logger.warning("Failed to fetch item %d, skipping", item_id)
        return None


def fetch_top_articles(count: int = 5) -> list[Article]:
    """Fetch top HN stories sorted by score, filtered for tech content.

    This is the original entry point kept for backward compatibility.
    """
    return fetch_tech_articles(count=count)


def fetch_tech_articles(count: int = 5) -> list[Article]:
    """Fetch top HN stories sorted by score, filtered for tech content."""
    logger.info("Fetching top stories from HN API...")
    story_ids = _get_with_retry(f"{HN_API_BASE}/topstories.json")

    # Fetch more candidates to have room after filtering
    story_ids = story_ids[:PREFETCH_COUNT]
    logger.info("Fetching details for %d stories...", len(story_ids))

    items = []
    for sid in story_ids:
        item = _fetch_item(sid)
        if item and item.get("type") == "story":
            title = item.get("title", "")
            if _is_tech_related(title):
                items.append(item)
            else:
                logger.info("Filtered out non-tech: '%s'", title)

    # Sort by score descending
    items.sort(key=lambda x: x.get("score", 0), reverse=True)

    articles = []
    for item in items[:count]:
        hn_url = f"https://news.ycombinator.com/item?id={item['id']}"
        url = item.get("url", hn_url)
        articles.append(
            Article(
                title=item.get("title", "Untitled"),
                url=url,
                hn_url=hn_url,
                score=item.get("score", 0),
                comment_count=item.get("descendants", 0),
                topic=Topic.TECH,
                summary="",
            )
        )

    logger.info("Fetched %d tech articles (filtered from %d candidates)", len(articles), len(story_ids))
    return articles


def fetch_stocks_articles(count: int = 5) -> list[Article]:
    """Fetch stock market articles. Placeholder — not yet configured."""
    logger.info("Stocks source not configured yet")
    return []


def fetch_realestate_articles(count: int = 5) -> list[Article]:
    """Fetch real estate articles. Placeholder — not yet configured."""
    logger.info("Realestate source not configured yet")
    return []


def fetch_articles_by_topic(topic: Topic, count: int = 5) -> list[Article]:
    """Dispatch to the appropriate fetcher based on topic.

    Args:
        topic: The Topic enum value to fetch articles for.
        count: Number of articles to fetch.

    Returns:
        List of Article objects for the given topic.
    """
    dispatchers = {
        Topic.TECH: fetch_tech_articles,
        Topic.STOCKS: fetch_stocks_articles,
        Topic.REALESTATE: fetch_realestate_articles,
    }

    fetcher = dispatchers.get(topic)
    if fetcher is None:
        logger.warning("Unknown topic: %s", topic)
        return []

    return fetcher(count=count)
