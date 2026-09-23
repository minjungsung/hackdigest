"""Topic-based article fetcher dispatcher."""

import logging

from src.models import Article, Language, Topic
from src.fetchers.tech import fetch_tech_articles
from src.fetchers.stocks import fetch_stocks_articles
from src.fetchers.realestate import fetch_realestate_articles

logger = logging.getLogger(__name__)

# Re-export individual fetchers for direct use
__all__ = [
    "fetch_articles_by_topic",
    "fetch_tech_articles",
    "fetch_stocks_articles",
    "fetch_realestate_articles",
]

# Topics where language affects which articles to fetch
LANGUAGE_DEPENDENT_TOPICS = {Topic.REALESTATE}


def fetch_articles_by_topic(topic: Topic, count: int = 5, language: Language = Language.EN) -> list[Article]:
    """Dispatch to the appropriate fetcher based on topic.

    For language-dependent topics (e.g., realestate), the language parameter
    determines which regional source to fetch from.

    Args:
        topic: The Topic enum value to fetch articles for.
        count: Number of articles to fetch.
        language: Language preference (affects source selection for some topics).

    Returns:
        List of Article objects for the given topic.
    """
    if topic == Topic.REALESTATE:
        return fetch_realestate_articles(count=count, language=language)

    dispatchers = {
        Topic.TECH: fetch_tech_articles,
        Topic.STOCKS: fetch_stocks_articles,
    }

    fetcher = dispatchers.get(topic)
    if fetcher is None:
        logger.warning("Unknown topic: %s", topic)
        return []

    return fetcher(count=count)
