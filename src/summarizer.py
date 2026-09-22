"""Extract and summarize article content with Korean translation."""

import html
import logging
import re

import trafilatura

from src.models import Article

logger = logging.getLogger(__name__)

MAX_SENTENCES = 3
MAX_CHARS = 500


def _strip_html(text: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in sentences if s.strip()]


def _truncate_sentences(sentences: list[str]) -> str:
    """Select up to MAX_SENTENCES within character limit."""
    selected = []
    total_chars = 0

    for sent in sentences[:MAX_SENTENCES]:
        if total_chars + len(sent) > MAX_CHARS and selected:
            break
        selected.append(sent)
        total_chars += len(sent)

    return " ".join(selected)


def _translate_to_korean(text: str) -> str:
    """Translate English text to Korean.

    Tries deep-translator (Google), then argostranslate (offline), then falls back to English.
    """
    # Attempt 1: deep-translator (Google Translate — best quality, needs internet)
    try:
        from deep_translator import GoogleTranslator
        translated = GoogleTranslator(source="en", target="ko").translate(text)
        if translated and translated.strip():
            logger.info("Translated via Google Translate")
            return translated
    except Exception as e:
        logger.warning("Google Translate failed: %s", e)

    # Attempt 2: argostranslate (offline, decent quality)
    try:
        import argostranslate.translate
        translated = argostranslate.translate.translate(text, "en", "ko")
        if translated and translated.strip():
            logger.info("Translated via Argos (offline)")
            return translated
    except Exception as e:
        logger.warning("Argos translate failed: %s", e)

    # Fallback: return English original
    logger.warning("All translation methods failed, using English original")
    return text


def summarize(article: Article, hn_text: str = "") -> None:
    """Extract body text from article URL and create a 3-sentence Korean summary.

    Modifies article.summary in place.

    Args:
        article: Article to summarize.
        hn_text: Raw HTML text from HN API (for Ask HN, Show HN posts).
    """
    body = ""

    # For Ask HN / Show HN posts with no external URL
    if hn_text and article.url == article.hn_url:
        body = _strip_html(hn_text)
        logger.info("Using HN text field for: %s", article.title)
    else:
        try:
            logger.info("Fetching content from: %s", article.url)
            downloaded = trafilatura.fetch_url(article.url)
            if downloaded:
                extracted = trafilatura.extract(downloaded)
                if extracted:
                    body = extracted
        except Exception as e:
            logger.warning("Failed to extract content from %s: %s", article.url, e)

    if not body:
        article.summary = "Failed to retrieve content."
        return

    sentences = _split_sentences(body)
    if not sentences:
        article.summary = "Failed to retrieve content."
        return

    english_summary = _truncate_sentences(sentences)
    article.summary = _translate_to_korean(english_summary)
    logger.info("Summarized '%s': %d chars", article.title, len(article.summary))
