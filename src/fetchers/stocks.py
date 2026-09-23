"""Fetch stock market news from Yahoo Finance RSS (EN) or Google News Korea (KO)."""

import logging
import re

import feedparser

from src.models import Article, Language, Topic

logger = logging.getLogger(__name__)

# US stock RSS sources (English)
US_STOCK_FEEDS = [
    ("Yahoo Finance", "https://finance.yahoo.com/news/rssurl"),
]

# Korean stock RSS sources (Korean)
KR_STOCK_FEEDS = [
    ("Google 주식+코스피", "https://news.google.com/rss/search?q=주식+코스피+코스닥&hl=ko&gl=KR&ceid=KR:ko"),
    ("Google 증시+주가", "https://news.google.com/rss/search?q=증시+주가+상장&hl=ko&gl=KR&ceid=KR:ko"),
]

# Filter for US stock/market-related keywords in titles
US_STOCK_KEYWORDS = re.compile(
    r"\b("
    r"stock|market|s&p|nasdaq|dow|nyse|earnings|dividend|ipo|"
    r"bull|bear|rally|crash|trading|investor|portfolio|"
    r"fed|interest rate|inflation|gdp|recession|"
    r"etf|bond|treasury|yield|hedge fund|"
    r"wall street|sec|ftc|"
    r"bitcoin|crypto|ethereum"
    r")\b",
    re.IGNORECASE,
)

# Filter for Korean stock/market-related keywords
KR_STOCK_KEYWORDS = re.compile(
    r"("
    r"주식|코스피|코스닥|증시|주가|상장|배당|IPO|공모주|"
    r"시가총액|매수|매도|종목|ETF|펀드"
    r")"
)


def _is_stock_related(title: str, language: Language = Language.EN) -> bool:
    """Return True if the article title is related to stocks/finance."""
    if language == Language.KO:
        return bool(KR_STOCK_KEYWORDS.search(title))
    return bool(US_STOCK_KEYWORDS.search(title))


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


def fetch_stocks_articles(count: int = 5, language: Language = Language.EN) -> list[Article]:
    """Fetch stock market news from RSS feeds based on language.

    Korean: Korean stock news from Google News Korea.
    English: US stock news from Yahoo Finance RSS.
    """
    feeds = KR_STOCK_FEEDS if language == Language.KO else US_STOCK_FEEDS
    logger.info("Fetching %s stock news from %d RSS sources...",
                "Korean" if language == Language.KO else "US", len(feeds))

    all_entries = _fetch_from_feeds(feeds)

    if not all_entries:
        logger.warning("No entries found from any stock RSS source")
        return []

    # Filter for stock relevance
    filtered = [e for e in all_entries if _is_stock_related(e.get("title", ""), language)]
    logger.info("Filtered %d stock articles from %d total", len(filtered), len(all_entries))

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
                topic=Topic.STOCKS,
                summary="",
            )
        )

    logger.info("Fetched %d stock articles (%s)", len(articles),
                "KR" if language == Language.KO else "US")
    return articles
