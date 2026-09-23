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

# Impact keywords that indicate a "hot" story
KR_IMPACT_KEYWORDS = re.compile(
    r"(급등|급락|폭등|폭락|역대|최고|최저|최대|최다|사상|신기록|속보|긴급|"
    r"충격|파격|돌파|붕괴|위기|전망|예측|반등|하락|상승|급변|"
    r"서울|강남|수도권|수억|억대)"
)

EN_IMPACT_KEYWORDS = re.compile(
    r"\b(surge|crash|record|historic|breaking|crisis|plunge|soar|"
    r"skyrocket|tumble|unprecedented|boom|bust|bubble|worst|best|"
    r"highest|lowest|spike|collapse|forecast)\b",
    re.IGNORECASE,
)


def _is_realestate_related(title: str, language: Language = Language.EN) -> bool:
    """Return True if the article title is related to real estate."""
    if language == Language.KO:
        return bool(KR_REALESTATE_KEYWORDS.search(title))
    return bool(US_REALESTATE_KEYWORDS.search(title))


def _score_article(title: str, source_count: int, language: Language) -> int:
    """Score an article by impact keywords + multi-source appearance."""
    score = 0
    # Multi-source bonus: appears in multiple feeds = hot story
    score += (source_count - 1) * 10

    # Impact keyword bonus
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


def fetch_realestate_articles(count: int = 5, language: Language = Language.EN) -> list[Article]:
    """Fetch real estate news from RSS feeds based on language.

    Korean: Korean real estate news from Google News Korea.
    English: US real estate news from Zillow, HousingWire, CNBC.

    Articles are ranked by impact keywords and multi-source appearance.
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

    # Deduplicate by title similarity and count sources per story
    # Normalize title for dedup: lowercase, strip source suffix like " - 조선비즈"
    def _normalize(title: str) -> str:
        title = re.sub(r"\s*[-–—|]\s*[^-–—|]+$", "", title)  # strip source suffix
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
        best_entry = entries[0]  # pick first occurrence
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
                topic=Topic.REALESTATE,
                summary="",
            )
        )
        logger.info("  [score=%d] %s", score, title[:60])

    logger.info("Fetched %d real estate articles (%s)",
                len(articles), "KR" if language == Language.KO else "US")
    return articles
