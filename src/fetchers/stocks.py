"""Fetch stock market news from Yahoo Finance RSS."""

import logging
import re

import feedparser

from src.models import Article, Topic

logger = logging.getLogger(__name__)

YAHOO_FINANCE_RSS = "https://finance.yahoo.com/news/rssurl"

# Filter for stock/market-related keywords in titles
STOCK_KEYWORDS = re.compile(
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


def _is_stock_related(title: str) -> bool:
    """Return True if the article title is related to stocks/finance."""
    return bool(STOCK_KEYWORDS.search(title))


def fetch_stocks_articles(count: int = 5) -> list[Article]:
    """Fetch stock market news from Yahoo Finance RSS, filtered for relevance."""
    logger.info("Fetching stock news from Yahoo Finance RSS...")

    try:
        feed = feedparser.parse(YAHOO_FINANCE_RSS)
    except Exception as e:
        logger.error("Failed to parse Yahoo Finance RSS: %s", e)
        return []

    if not feed.entries:
        logger.warning("No entries found in Yahoo Finance RSS")
        return []

    # Filter for stock/market-related articles
    filtered = [e for e in feed.entries if _is_stock_related(e.get("title", ""))]
    logger.info("Filtered %d stock-related articles from %d total", len(filtered), len(feed.entries))

    # Take top N (RSS is already sorted by recency)
    articles = []
    for entry in filtered[:count]:
        title = entry.get("title", "Untitled")
        url = entry.get("link", "")
        articles.append(
            Article(
                title=title,
                url=url,
                hn_url=url,  # No HN discussion URL for stock articles
                score=0,
                comment_count=0,
                topic=Topic.STOCKS,
                summary="",
            )
        )

    logger.info("Fetched %d stock articles", len(articles))
    return articles
