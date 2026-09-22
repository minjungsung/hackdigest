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

SUMMARY_PROMPT = """You are a Korean tech blogger writing for developer friends.
Summarize the given article in 3 sentences in Korean.
Use a casual, natural tone like you're explaining to a coworker over coffee — not like a news anchor or AI.
Avoid stiff expressions like "~했습니다", "~입니다". Use "~했어요", "~한 거예요", "~인 셈이죠" etc.
Be specific about the tech details, not vague.
Output ONLY the Korean summary, nothing else."""


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


def _summarize_from_title_with_groq(title: str, url: str) -> str:
    """Use Groq LLM to explain a topic based on title alone, using its own knowledge."""
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        return ""

    prompt = f"""Based on the article title and URL below, explain what this is about in 3 sentences in Korean.
Use your own knowledge to provide useful context about the topic.
Use a casual, natural tone — like explaining to a developer friend, not writing a formal report.
Avoid stiff expressions like "~했습니다". Use "~했어요", "~한 거예요", "~인 셈이죠" etc.
Output ONLY the Korean explanation, nothing else.

Title: {title}
URL: {url}"""

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
                    {"role": "system", "content": "You are a Korean tech blogger who explains tech topics in a casual, friendly tone for developer friends."},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 400,
                "temperature": 0.3,
            },
            timeout=20,
        )
        resp.raise_for_status()
        result = resp.json()["choices"][0]["message"]["content"].strip()
        logger.info("Groq explained topic '%s' from title: %d chars", title, len(result))
        return result
    except Exception as e:
        logger.warning("Groq title-based explanation failed for '%s': %s", title, e)
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

    # 2. Fallback: use LLM knowledge to explain the topic from title
    if not body or len(body) < MIN_USEFUL_LENGTH:
        logger.info("Extraction insufficient for '%s', using LLM knowledge...", article.title)
        explanation = _summarize_from_title_with_groq(article.title, article.url)
        if explanation:
            article.summary = explanation
            return

    # 3. If still no content, give up
    if not body or len(body) < MIN_USEFUL_LENGTH:
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
