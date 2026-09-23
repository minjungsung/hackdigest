"""Fetch real estate news from multiple RSS sources."""

import logging
import re

import feedparser

from src.models import Article, Topic

logger = logging.getLogger(__name__)

# Multiple RSS sources for broader coverage
REALESTATE_FEEDS = [
    ("Zillow Research", "https://www.zillow.com/research/feed/"),
    ("HousingWire", "https://www.housingwire.com/feed/"),
    ("CNBC Real Estate", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000115"),
]

# Filter for real estate / housing keywords
REALESTATE_KEYWORDS = re.compile(
    r"\b("
    r"housing|home|house|apartment|condo|rent|mortgage|"
    r"real estate|property|residential|commercial property|"
    r"interest rate|fed rate|refinance|loan|"
    r"construction|building permit|zoning|"
    r"buyer|seller|listing|inventory|affordability|"
    r"zillow|redfin|realtor|mls|"
    r"foreclosure|eviction|landlord|tenant"
    r")\b",
    re.IGNORECASE,
)


def _is_realestate_related(title: str) -> bool:
    """Return True if the article title is related to real estate."""
    return bool(REALESTATE_KEYWORDS.search(title))


def fetch_realestate_articles(count: int = 5) -> list[Article]:
    """Fetch real estate news from multiple RSS feeds, deduplicated and filtered."""
    logger.info("Fetching real estate news from %d RSS sources...", len(REALESTATE_FEEDS))

    all_entries = []
    for source_name, feed_url in REALESTATE_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            entries = feed.entries or []
            logger.info("  %s: %d entries", source_name, len(entries))
            for entry in entries:
                entry["_source"] = source_name
            all_entries.extend(entries)
        except Exception as e:
            logger.warning("Failed to fetch %s: %s", source_name, e)

    if not all_entries:
        logger.warning("No entries found from any real estate RSS source")
        return []

    # Filter for real estate relevance
    filtered = [e for e in all_entries if _is_realestate_related(e.get("title", ""))]
    logger.info("Filtered %d real estate articles from %d total", len(filtered), len(all_entries))

    # Deduplicate by URL
    seen_urls = set()
    unique = []
    for entry in filtered:
        url = entry.get("link", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique.append(entry)

    # Take top N
    articles = []
    for entry in unique[:count]:
        title = entry.get("title", "Untitled")
        url = entry.get("link", "")
        source = entry.get("_source", "")
        articles.append(
            Article(
                title=f"{title}",
                url=url,
                hn_url=url,  # No discussion URL for real estate articles
                score=0,
                comment_count=0,
                topic=Topic.REALESTATE,
                summary="",
            )
        )

    logger.info("Fetched %d real estate articles", len(articles))
    return articles
