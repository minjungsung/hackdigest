"""Identify repeated items within a single digest, without delivery history."""

import html
import re
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from src.models import Article


def canonical_url(url: str) -> str:
    parsed = urlsplit(url)
    query = urlencode(sorted((key, value) for key, value in parse_qsl(parsed.query)
                             if not key.lower().startswith("utm_") and key.lower() not in {"ref", "fbclid", "gclid"}))
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), query, ""))


def normalized_title(title: str) -> str:
    title = re.sub(r"\s+[-–—]\s+(?:Reuters|TechCrunch|Bloomberg(?:\.com)?|The Verge|Ars Technica|VentureBeat|Business Insider)$", "", title, flags=re.I)
    return re.sub(r"[^\w]+", " ", html.unescape(title).casefold()).strip()


def same_item(first: Article, second: Article) -> bool:
    """Match links, identical headlines, and close headline variants."""
    if first.url and second.url and canonical_url(first.url) == canonical_url(second.url):
        return True
    left, right = normalized_title(first.title), normalized_title(second.title)
    if not left or not right:
        return False
    # Several publishers can describe the same concrete corporate event with
    # very different headlines. Collapse these identifiable event anchors.
    def event_key(text: str):
        companies = re.findall(r"\b(openai|anthropic|cohere|mistral|deepseek|moonshot|minimax|baidu|tencent|bytedance)\b", text)
        if "ipo" in text.split() and companies:
            return ("ipo", tuple(sorted(set(companies))))
        if re.search(r"\b(?:alibaba|qwen\w*)\b", text) and re.search(r"beijing|phone home|exfiltrat", text):
            return ("qwen", "reported-data-transfer")
        return None
    first_event, second_event = event_key(left), event_key(right)
    if first_event and first_event == second_event:
        return True
    if left == right or SequenceMatcher(None, left, right).ratio() >= 0.86:
        if set(re.findall(r"\d+(?:[. ]\d+)*", left)) == set(re.findall(r"\d+(?:[. ]\d+)*", right)):
            return True
    if set(re.findall(r"\d+", left)) != set(re.findall(r"\d+", right)):
        return False
    stopwords = {"a", "an", "the", "and", "or", "to", "of", "in", "for", "with", "its", "is", "on", "ai", "model", "models", "says", "new"}
    left_words, right_words = set(left.split()) - stopwords, set(right.split()) - stopwords
    overlap = len(left_words & right_words)
    return overlap >= 4 and overlap / max(1, min(len(left_words), len(right_words))) >= 0.7


def deduplicate(articles: list[Article]) -> list[Article]:
    selected = []
    for article in articles:
        if not any(same_item(article, existing) for existing in selected):
            selected.append(article)
    return selected
