"""Fetch real estate news from multiple RSS sources."""

import logging
import re

import feedparser

from src.models import Article, Language, Topic

logger = logging.getLogger(__name__)

# US real estate RSS sources (for English subscribers)
US_REALESTATE_FEEDS = [
    ("Zillow Research", "https://www.zillow.com/research/feed/"),
    ("HousingWire", "https://www.housingwire.com/feed/"),
    ("CNBC Real Estate", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000115"),
]

# Korean real estate RSS sources (for Korean subscribers)
KR_REALESTATE_FEEDS = [
    ("Google 부동산", "https://news.google.com/rss/search?q=부동산+아파트+매매&hl=ko&gl=KR&ceid=KR:ko"),
    ("Google 부동산+전세", "https://news.google.com/rss/search?q=부동산+전세+분양&hl=ko&gl=KR&ceid=KR:ko"),
]

# Filter for US real estate keywords
US_REALESTATE_KEYWORDS = re.compile(
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

# Filter for Korean real estate keywords
KR_REALESTATE_KEYWORDS = re.compile(
    r"("
    r"부동산|아파트|매매|전세|월세|분양|"
    r"재건축|재개발|청약|입주|"
    r"주택|오피스텔|빌라|상가|토지|"
    r"대출|금리|담보|LTV|DSR|"
    r"공시지가|실거래|매물|호가"
    r")"
)


def _is_realestate_related(title: str, language: Language = Language.EN) -> bool:
    """Return True if the article title is related to real estate."""
    if language == Language.KO:
        return bool(KR_REALESTATE_KEYWORDS.search(title))
    return bool(US_REALESTATE_KEYWORDS.search(title))


def _fetch_from_feeds(feeds: list[tuple[str, str]]) -> list[dict]:
    """Fetch entries from multiple RSS feeds."""
    all_entries = []
    for source_name, feed_url in feeds:
        try:
            feed = feedparser.parse(feed_url)
            entries = feed.entries or []
            logger.info("  %s: %d entries", source_name, len(entries))
            for entry in entries:
                entry["_source"] = source_name
            all_entries.extend(entries)
        except Exception as e:
            logger.warning("Failed to fetch %s: %s", source_name, e)
    return all_entries


def fetch_realestate_articles(count: int = 5, language: Language = Language.EN) -> list[Article]:
    """Fetch real estate news from RSS feeds based on language.

    Korean: Korean real estate news from Google News Korea.
    English: US real estate news from Zillow, HousingWire, CNBC.
    """
    feeds = KR_REALESTATE_FEEDS if language == Language.KO else US_REALESTATE_FEEDS
    logger.info("Fetching %s real estate news from %d RSS sources...",
                "Korean" if language == Language.KO else "US", len(feeds))

    all_entries = _fetch_from_feeds(feeds)

    if not all_entries:
        logger.warning("No entries found from any real estate RSS source")
        return []

    # Filter for real estate relevance
    filtered = [e for e in all_entries if _is_realestate_related(e.get("title", ""), language)]
    logger.info("Filtered %d real estate articles from %d total", len(filtered), len(all_entries))

    # If no filtered results for Korean, use all entries (Google News search is already filtered)
    if not filtered and language == Language.KO:
        filtered = all_entries
        logger.info("Using all %d entries (Google News already filtered)", len(filtered))

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
        articles.append(
            Article(
                title=title,
                url=url,
                hn_url=url,
                score=0,
                comment_count=0,
                topic=Topic.REALESTATE,
                summary="",
            )
        )

    logger.info("Fetched %d real estate articles (%s)", len(articles),
                "KR" if language == Language.KO else "US")
    return articles
