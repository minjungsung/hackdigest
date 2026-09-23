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

# Impact keywords that indicate a "hot" story
KR_IMPACT_KEYWORDS = re.compile(
    r"(급등|급락|폭등|폭락|역대|최고|최저|최대|최다|사상|신기록|속보|긴급|"
    r"충격|파격|돌파|붕괴|위기|전망|예측|반등|하락|상승|급변|"
    r"삼성|SK|현대|LG|카카오|네이버|셀트리온|삼성전자)"
)

EN_IMPACT_KEYWORDS = re.compile(
    r"\b(surge|crash|record|historic|breaking|plunge|soar|"
    r"skyrocket|tumble|unprecedented|boom|bust|worst|best|"
    r"highest|lowest|spike|collapse|rally|forecast|"
    r"apple|tesla|nvidia|amazon|google|meta|microsoft)\b",
    re.IGNORECASE,
)


def _is_stock_related(title: str, language: Language = Language.EN) -> bool:
    """Return True if the article title is related to stocks/finance."""
    if language == Language.KO:
        return bool(KR_STOCK_KEYWORDS.search(title))
    return bool(US_STOCK_KEYWORDS.search(title))


def _score_article(title: str, source_count: int, language: Language) -> int:
    """Score an article by impact keywords + multi-source appearance."""
    score = 0
    score += (source_count - 1) * 10

    if language == Language.KO:
        score += len(KR_IMPACT_KEYWORDS.findall(title)) * 5
    else:
        score += len(EN_IMPACT_KEYWORDS.findall(title)) * 5

    return score


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

    Articles are ranked by impact keywords and multi-source appearance.
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

    # Deduplicate by title similarity and count sources per story
    def _normalize(title: str) -> str:
        title = re.sub(r"\s*[-–—|]\s*[^-–—|]+$", "", title)
        return title.strip().lower()

    title_groups: dict[str, list[dict]] = {}
    for entry in filtered:
        norm = _normalize(entry.get("title", ""))
        if norm not in title_groups:
            title_groups[norm] = []
        title_groups[norm].append(entry)

    # Score and rank
    scored: list[tuple[int, dict]] = []
    for norm_title, entries in title_groups.items():
        best_entry = entries[0]
        source_count = len(set(e.get("_source", "") for e in entries))
        score = _score_article(best_entry.get("title", ""), source_count, language)
        scored.append((score, best_entry))

    scored.sort(key=lambda x: x[0], reverse=True)

    # Take top N
    articles = []
    for score, entry in scored[:count]:
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
        logger.info("  [score=%d] %s", score, title[:60])

    logger.info("Fetched %d stock articles (%s)",
                len(articles), "KR" if language == Language.KO else "US")
    return articles
