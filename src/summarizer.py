"""Extract and summarize article content using Groq LLM."""

import html
import logging
import os
import re

import requests
import trafilatura

from src.models import Article

logger = logging.getLogger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "qwen/qwen3.8-27b"
MAX_INPUT_CHARS = 3000  # Limit input text to avoid token overflow
MIN_USEFUL_LENGTH = 100

HN_API_BASE = "https://hacker-news.firebaseio.com/v0"

SUMMARY_PROMPT = """You are a tech news summarizer. Summarize the given article text in 3 concise sentences in Korean.
Focus on the key technical insight or news value. Be specific, not vague.
Output ONLY the Korean summary, nothing else. No labels, no prefixes."""


def _strip_html(text: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_body(article: Article, hn_text: str = "") -> str:
    """Extract article body text from URL or HN text field."""
    # For Ask HN / Show HN posts with no external URL
    if hn_text and article.url == article.hn_url:
        body = _strip_html(hn_text)
        logger.info("Using HN text field for: %s", article.title)
        return body

    try:
        logger.info("Fetching content from: %s", article.url)
        downloaded = trafilatura.fetch_url(article.url)
        if downloaded:
            extracted = trafilatura.extract(
                downloaded,
                include_comments=False,
                include_tables=False,
                no_fallback=False,
            )
            if extracted and len(extracted) >= MIN_USEFUL_LENGTH:
                return extracted
    except Exception as e:
        logger.warning("Failed to extract content from %s: %s", article.url, e)

    return ""


def _fetch_hn_top_comment(item_id: int) -> str:
    """Fetch the top comment from a HN story as fallback content."""
    try:
        resp = requests.get(f"{HN_API_BASE}/item/{item_id}.json", timeout=10)
        resp.raise_for_status()
        story = resp.json()
        kids = story.get("kids", [])
        if not kids:
            return ""

        comment_resp = requests.get(f"{HN_API_BASE}/item/{kids[0]}.json", timeout=10)
        comment_resp.raise_for_status()
        comment = comment_resp.json()
        text = comment.get("text", "")
        if text:
            clean = _strip_html(text)
            if len(clean) >= MIN_USEFUL_LENGTH:
                return clean
    except Exception as e:
        logger.warning("Failed to fetch top comment for item %d: %s", item_id, e)
    return ""


def _extract_item_id(hn_url: str) -> int | None:
    """Extract HN item ID from URL."""
    match = re.search(r"id=(\d+)", hn_url)
    return int(match.group(1)) if match else None


def _summarize_with_groq(text: str, title: str) -> str:
    """Use Groq API to summarize text in Korean."""
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        logger.warning("GROQ_API_KEY not set, falling back to truncation")
        return ""

    # Truncate input to avoid token limits
    truncated = text[:MAX_INPUT_CHARS]

    try:
        resp = requests.post(
            GROQ_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": GROQ_MODEL,
                "messages": [
                    {"role": "system", "content": SUMMARY_PROMPT},
                    {"role": "user", "content": f"Article title: {title}\n\n{truncated}"},
                ],
                "max_tokens": 400,
                "temperature": 0.3,
            },
            timeout=20,
        )
        resp.raise_for_status()
        result = resp.json()["choices"][0]["message"]["content"].strip()
        logger.info("Groq summarized '%s': %d chars", title, len(result))
        return result
    except Exception as e:
        logger.warning("Groq API failed for '%s': %s", title, e)
        return ""


def _fallback_summary(text: str) -> str:
    """Simple truncation fallback when LLM is unavailable."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    selected = []
    total = 0
    for s in sentences[:5]:
        s = s.strip()
        if len(s) < 20:
            continue
        if total + len(s) > 800:
            break
        selected.append(s)
        total += len(s)
    return " ".join(selected) if selected else text[:500]


def summarize(article: Article, hn_text: str = "") -> None:
    """Extract body text and create a Korean summary using Groq LLM.

    Falls back to top HN comment if article extraction fails.
    Falls back to simple truncation if Groq API is unavailable.

    Modifies article.summary in place.
    """
    # 1. Try extracting article body
    body = _extract_body(article, hn_text)

    # 2. Fallback to top HN comment if extraction failed
    if not body or len(body) < MIN_USEFUL_LENGTH:
        logger.info("Extraction insufficient for '%s', trying top HN comment...", article.title)
        item_id = _extract_item_id(article.hn_url)
        if item_id:
            body = _fetch_hn_top_comment(item_id)

    # 3. If still no content, give up
    if not body:
        article.summary = "요약을 생성할 수 없습니다. 링크를 클릭해 원문을 확인하세요."
        logger.warning("No content available for '%s'", article.title)
        return

    # 4. Summarize with Groq (Korean)
    summary = _summarize_with_groq(body, article.title)
    if summary:
        article.summary = summary
        return

    # 5. Fallback to simple truncation (English)
    article.summary = _fallback_summary(body)
    logger.info("Used fallback summary for '%s': %d chars", article.title, len(article.summary))
