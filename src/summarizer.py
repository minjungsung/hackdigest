"""Extract and summarize article content using Groq LLM."""

import html
import logging
import os
import re

import requests
import trafilatura

from src.models import Article, Language

logger = logging.getLogger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "qwen/qwen3.8-27b"
MAX_INPUT_CHARS = 3000  # Limit input text to avoid token overflow
MIN_USEFUL_LENGTH = 100

HN_API_BASE = "https://hacker-news.firebaseio.com/v0"

SUMMARY_PROMPT_KO = """You are a Korean tech blogger writing for developer friends.
Summarize the given article in 3 sentences in Korean.
Use a casual, natural tone like you're explaining to a coworker over coffee — not like a news anchor or AI.
Avoid stiff expressions like "~했습니다", "~입니다". Use "~했어요", "~한 거예요", "~인 셈이죠" etc.
Be specific about the tech details, not vague.
Output ONLY the Korean summary, nothing else."""

SUMMARY_PROMPT_EN = """Summarize the given article in 3 sentences in English. Use a casual, friendly tone. Be specific about the tech details. Output ONLY the English summary, nothing else."""


def _strip_html(text: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _call_groq(system: str, user: str, max_tokens: int = 400) -> str:
    """Call Groq API with system and user messages. Returns empty string on failure."""
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        return ""

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
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.3,
            },
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.warning("Groq API call failed: %s", e)
        return ""


def _translate_title(title: str, language: Language) -> str:
    """Translate article title to the target language using Groq LLM."""
    if language == Language.EN:
        return title  # Most titles are already English

    result = _call_groq(
        system="You are a translator. Translate the given English title to Korean. Keep it concise and natural. Output ONLY the translated title, nothing else.",
        user=title,
        max_tokens=100,
    )

    if result:
        logger.info("Translated title: '%s' -> '%s'", title, result)
        return result

    return title  # Return original on failure


def _extract_body(article: Article, hn_text: str = "") -> str:
    """Extract article body text from URL or HN text field."""
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


def _summarize_from_title(title: str, url: str, language: Language) -> str:
    """Use Groq LLM to explain a topic based on title alone, using its own knowledge."""
    if language == Language.EN:
        prompt = f"""Based on the article title and URL below, explain what this is about in 3 sentences in English.
Use your own knowledge to provide useful context about the topic.
Use a casual, friendly tone — like explaining to a developer friend.
Output ONLY the English explanation, nothing else.

Title: {title}
URL: {url}"""
        system = "You are a tech blogger who explains topics in a casual, friendly tone."
    else:
        prompt = f"""Based on the article title and URL below, explain what this is about in 3 sentences in Korean.
Use your own knowledge to provide useful context about the topic.
Use a casual, natural tone — like explaining to a developer friend.
Avoid stiff expressions like "~했습니다". Use "~했어요", "~한 거예요", "~인 셈이죠" etc.
Output ONLY the Korean explanation, nothing else.

Title: {title}
URL: {url}"""
        system = "You are a Korean tech blogger who explains topics in a casual, friendly tone."

    result = _call_groq(system, prompt)
    if result:
        logger.info("Groq explained '%s' from title: %d chars", title, len(result))
    return result


def _summarize_body(text: str, title: str, language: Language) -> str:
    """Use Groq API to summarize extracted body text in the specified language."""
    truncated = text[:MAX_INPUT_CHARS]
    prompt = SUMMARY_PROMPT_EN if language == Language.EN else SUMMARY_PROMPT_KO
    result = _call_groq(prompt, f"Article title: {title}\n\n{truncated}")
    if result:
        logger.info("Groq summarized '%s': %d chars", title, len(result))
    return result


def _fallback_summary(text: str, language: Language) -> str:
    """Fallback: try LLM translation of truncated text, or simple truncation."""
    # First try: ask LLM to summarize the truncated text
    truncated = text[:800]

    if language == Language.KO:
        result = _call_groq(
            system="Translate and summarize the following English text into 3 sentences in Korean. Use casual tone. Output ONLY Korean text.",
            user=truncated,
        )
        if result:
            logger.info("Fallback LLM translation succeeded: %d chars", len(result))
            return result

    # Last resort: plain truncation
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


def summarize(article: Article, hn_text: str = "", language: Language = Language.KO) -> None:
    """Extract body text, summarize in the target language, and translate title.

    Modifies article.title and article.summary in place.
    """
    # Translate title
    article.title = _translate_title(article.title, language)

    # 1. Try extracting article body
    body = _extract_body(article, hn_text)

    # 2. Fallback: use LLM knowledge to explain from title
    if not body or len(body) < MIN_USEFUL_LENGTH:
        logger.info("Extraction insufficient for '%s', using LLM knowledge...", article.title)
        explanation = _summarize_from_title(article.title, article.url, language)
        if explanation:
            article.summary = explanation
            return

    # 3. If still no content, give up
    if not body or len(body) < MIN_USEFUL_LENGTH:
        if language == Language.EN:
            article.summary = "Unable to generate summary. Click the link to read the original article."
        else:
            article.summary = "요약을 생성할 수 없습니다. 링크를 클릭해 원문을 확인하세요."
        logger.warning("No content available for '%s'", article.title)
        return

    # 4. Summarize with Groq
    summary = _summarize_body(body, article.title, language)
    if summary:
        article.summary = summary
        return

    # 5. Fallback — try LLM translation, then plain truncation
    article.summary = _fallback_summary(body, language)
    logger.info("Used fallback summary for '%s': %d chars", article.title, len(article.summary))
