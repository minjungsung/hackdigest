"""Fetch top stories from Hacker News API."""

import logging
import time

import requests

from src.models import Article

logger = logging.getLogger(__name__)

HN_API_BASE = "https://hacker-news.firebaseio.com/v0"
REQUEST_TIMEOUT = 10
MAX_RETRIES = 3
PREFETCH_COUNT = 30


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
    """Fetch top HN stories sorted by score, return top `count`."""
    logger.info("Fetching top stories from HN API...")
    story_ids = _get_with_retry(f"{HN_API_BASE}/topstories.json")

    # Only fetch top PREFETCH_COUNT to minimize API calls
    story_ids = story_ids[:PREFETCH_COUNT]
    logger.info("Fetching details for %d stories...", len(story_ids))

    items = []
    for sid in story_ids:
        item = _fetch_item(sid)
        if item and item.get("type") == "story":
            items.append(item)

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
                summary="",
            )
        )

    logger.info("Fetched %d articles", len(articles))
    return articles
