"""Collect recent LLM announcements, reporting, and research commentary."""

import calendar
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import requests

from src.models import Article, Topic

logger = logging.getLogger(__name__)
REQUEST_TIMEOUT = 15
FEEDS = (
    ("OpenAI", "official", "https://openai.com/news/rss.xml"),
    ("Google DeepMind", "official", "https://deepmind.google/blog/rss.xml"),
    ("Google DeepMind", "official", "https://blog.google/products/gemini/rss/"),
    ("TechCrunch", "reporting", "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("Sebastian Raschka", "analysis", "https://magazine.sebastianraschka.com/feed"),
    ("Simon Willison", "analysis", "https://simonwillison.net/atom/everything/"),
    ("Interconnects", "analysis", "https://www.interconnects.ai/feed"),
    ("Latent Space", "analysis", "https://www.latent.space/feed"),
    ("Import AI", "analysis", "https://www.importai.net/feed"),
    ("Ars Technica", "reporting", "https://feeds.arstechnica.com/arstechnica/technology-lab"),
    ("Hugging Face", "analysis", "https://huggingface.co/blog/feed.xml"),
)
NEWS_GROUPS = (
    "OpenAI OR Anthropic OR Gemini OR Mistral OR xAI",
    "Qwen OR DeepSeek OR Kimi OR Zhipu OR MiniMax OR StepFun",
    "Amazon Nova OR Microsoft Phi OR NVIDIA Nemotron OR IBM Granite OR Cohere OR AI21",
    "Baidu ERNIE OR Tencent Hunyuan OR ByteDance Doubao OR Apple AI OR AllenAI OLMo",
)
NEWS_PUBLISHERS = {
    "reuters.com", "bloomberg.com", "ft.com", "theinformation.com", "techcrunch.com",
    "theverge.com", "arstechnica.com", "wired.com", "venturebeat.com", "cnbc.com",
    "theguardian.com", "nytimes.com", "wsj.com", "semafor.com", "businessinsider.com",
    "technologyreview.com", "scmp.com", "bbc.com",
}
COMPANY_KEYWORDS = {
    "OpenAI": r"\b(?:openai|gpt[- ]?\d|astra|codex)\b",
    "Anthropic": r"\b(?:anthropic|claude)\b",
    "Gemini": r"\b(?:gemini|deepmind)\b",
    "Mistral": r"\b(?:mistral|codestral|ministral)\b",
    "DeepSeek": r"\bdeepseek\b",
    "xAI": r"\b(?:xai|grok)\b",
    "Qwen": r"\bqwen(?:\d|\b)",
    "Llama": r"\bllama(?:\d|\b)",
    "Amazon": r"\b(?:amazon|aws|nova)\b",
    "Microsoft": r"\b(?:microsoft|phi[- ]?\d|mai[- ]?\d)\b",
    "NVIDIA": r"\b(?:nvidia|nemotron)\b",
    "IBM": r"\b(?:ibm|granite)\b",
    "Cohere": r"\b(?:cohere|command[- ]?[ra])\b",
    "AI21": r"\b(?:ai21|jamba)\b",
    "Baidu": r"\b(?:baidu|ernie)\b",
    "Tencent": r"\b(?:tencent|hunyuan)\b",
    "ByteDance": r"\b(?:bytedance|doubao|seed[- ]?\d)\b",
    "Moonshot": r"\b(?:moonshot|kimi)\b",
    "Z.ai": r"\b(?:z\.ai|zhipu|glm[- ]?\d)\b",
    "MiniMax": r"\bminimax\b",
    "StepFun": r"\b(?:stepfun|step[- ]?\d)\b",
    "Apple": r"\bapple\b",
    "Allen AI": r"\b(?:allen ?ai|ai2|olmo)\b",
    "Hugging Face": r"\b(?:hugging ?face|smollm)\b",
}
COMPANIES = tuple(COMPANY_KEYWORDS)
MODEL_SEARCHES = ("Claude", "Grok", "Kimi", "GLM", "Nemotron", "Hunyuan", "Doubao", "ERNIE", "Nova", "OLMo")
SEARCH_GROUPS = {"Claude": "Anthropic", "Grok": "xAI", "Kimi": "Moonshot", "GLM": "Z.ai",
                 "Nemotron": "NVIDIA", "Hunyuan": "Tencent", "Doubao": "ByteDance",
                 "ERNIE": "Baidu", "Nova": "Amazon", "OLMo": "Allen AI"}
OFFICIAL_DOMAINS = {
    "openai.com", "anthropic.com", "deepmind.google", "blog.google",
    "ai.meta.com", "mistral.ai", "deepseek.com", "x.ai", "qwen.ai",
    "qwenlm.github.io",
    "aws.amazon.com", "amazon.science", "microsoft.com", "nvidia.com", "ibm.com",
    "cohere.com", "ai21.com", "baidu.com", "tencent.com", "bytedance.com",
    "moonshot.ai", "moonshot.cn", "z.ai", "minimax.io", "stepfun.com", "apple.com",
    "allenai.org",
}
MODEL_KEYWORDS = re.compile(
    r"\b(llm|language model|reasoning|transformer|gpt|astra|codex|claude|"
    r"gemini|llama|mistral|deepseek|grok|qwen|kimi|glm|nemotron|hunyuan|ernie|"
    r"olmo|jamba|nova|granite|model|agent|api|benchmark|ai|artificial intelligence)\b",
    re.IGNORECASE,
)


def canonical_url(url: str) -> str:
    """Ignore fragments and tracking queries when deduplicating article links."""
    parsed = urlsplit(url)
    query = urlencode(sorted((key, value) for key, value in parse_qsl(parsed.query)
                             if not key.lower().startswith("utm_") and key.lower() not in {"ref", "fbclid", "gclid"}))
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), query, ""))


def _official(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(host == domain or host.endswith("." + domain) for domain in OFFICIAL_DOMAINS)


def _feed_candidates(source: str, source_type: str, url: str, cutoff: float, now: float) -> list[tuple[float, str, Article]]:
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        entries = feedparser.parse(response.content).entries
        candidates = []
        for entry in entries:
            date = entry.get("published_parsed") or entry.get("updated_parsed")
            if not date:
                continue
            published = calendar.timegm(date)
            title, link = entry.get("title", "").strip(), entry.get("link", "")
            if not cutoff <= published <= now or not title or urlsplit(link).scheme not in ("http", "https"):
                continue
            if source_type == "official" and not _official(link):
                continue
            if not MODEL_KEYWORDS.search(title):
                continue
            group = source
            if source_type == "reporting":
                company = next((name for name, pattern in COMPANY_KEYWORDS.items()
                                if re.search(pattern, title, re.IGNORECASE)), None)
                if not company:
                    continue
                group = "Google DeepMind" if company == "Gemini" else company
            if source == "Google News":
                publisher = entry.get("source", {})
                host = (urlsplit(publisher.get("href", "")).hostname or "").lower()
                if not any(host == domain or host.endswith("." + domain) for domain in NEWS_PUBLISHERS):
                    continue
                source_name = publisher.get("title", host)
                title = re.sub(r"\s+[-–—]\s+" + re.escape(source_name) + r"$", "", title)
            else:
                source_name = source
            candidates.append((published, group, Article(
                title=title, url=link, hn_url="", score=0, comment_count=0,
                topic=Topic.TECH, section="llm", source=source_name, source_type=source_type,
            )))
        return candidates
    except (requests.RequestException, ValueError, TypeError) as exc:
        logger.warning("LLM feed unavailable (%s): %s", source, exc)
        return []


def _hn_candidates(company: str, cutoff: float, now: float) -> list[tuple[float, str, Article]]:
    try:
        response = requests.get("https://hn.algolia.com/api/v1/search_by_date", params={
            "query": company, "tags": "story", "restrictSearchableAttributes": "title",
            "numericFilters": f"created_at_i>={int(cutoff)},points>=20", "hitsPerPage": 30,
        }, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        candidates = []
        for item in response.json().get("hits", []):
            title, url = item.get("title") or "", item.get("url") or ""
            published = item.get("created_at_i", 0)
            if not cutoff <= published <= now or not MODEL_KEYWORDS.search(title):
                continue
            group = SEARCH_GROUPS.get(company, company)
            if not re.search(COMPANY_KEYWORDS[group], title, re.IGNORECASE):
                continue
            if urlsplit(url).scheme not in ("http", "https"):
                continue
            source = urlsplit(url).hostname or "Hacker News"
            candidates.append((published, "Google DeepMind" if group == "Gemini" else group, Article(
                title=title, url=url, hn_url=f"https://news.ycombinator.com/item?id={item['objectID']}",
                score=item.get("points") or 0, comment_count=item.get("num_comments") or 0,
                topic=Topic.TECH, section="llm", source=source,
                source_type="official" if _official(url) else "reporting",
            )))
        return candidates
    except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
        logger.warning("LLM story search unavailable (%s): %s", company, exc)
        return []


def fetch_llm_articles(count: int = 5, *, now: datetime | None = None) -> list[Article]:
    """Select recent articles from the past three days, with source diversity.

    Official feeds and targeted HN searches are independent: a failed source
    does not prevent delivery of results from the other sources.
    """
    if count <= 0:
        return []
    current = now or datetime.now(timezone.utc)
    cutoff = (current - timedelta(days=3)).timestamp()
    timestamp = current.timestamp()
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(_feed_candidates, *feed, cutoff, timestamp) for feed in FEEDS]
        for query in NEWS_GROUPS:
            feed_url = "https://news.google.com/rss/search?" + urlencode({
                "q": f"({query}) (AI OR LLM OR model) when:3d", "hl": "en-US", "gl": "US", "ceid": "US:en",
            })
            futures.append(pool.submit(_feed_candidates, "Google News", "reporting", feed_url, cutoff, timestamp))
        futures.extend(pool.submit(_hn_candidates, company, cutoff, timestamp) for company in (*COMPANIES, *MODEL_SEARCHES))
        candidates = [item for future in futures for item in future.result()]

    # Prefer original announcements over duplicate coverage of the same URL.
    candidates.sort(key=lambda item: (item[2].source_type == "official", item[0]), reverse=True)
    unique, seen_titles = {}, set()
    for candidate in candidates:
        title = re.sub(r"[^\w]+", " ", candidate[2].title.casefold()).strip()
        url = canonical_url(candidate[2].url)
        if url not in unique and title not in seen_titles:
            unique[url] = candidate
            seen_titles.add(title)
    ranked = sorted(unique.values(), key=lambda item: item[0], reverse=True)
    articles, source_counts = [], {}
    for _, company, article in ranked:
        if source_counts.get(company, 0) >= 2:
            continue
        articles.append(article)
        source_counts[company] = source_counts.get(company, 0) + 1
        if len(articles) == count:
            break
    logger.info("Selected %d recent LLM stories from %d candidates", len(articles), len(candidates))
    return articles
