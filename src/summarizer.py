"""Extract and summarize article content."""

import html
import logging
import re

import trafilatura

from src.models import Article

logger = logging.getLogger(__name__)

MAX_SENTENCES = 10
MIN_SENTENCES = 5
MAX_CHARS = 1000


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
    """Select 5-10 sentences within character limit."""
    selected = []
    total_chars = 0

    for sent in sentences[:MAX_SENTENCES]:
        if total_chars + len(sent) > MAX_CHARS and len(selected) >= MIN_SENTENCES:
            break
        selected.append(sent)
        total_chars += len(sent)

    return " ".join(selected)


def summarize(article: Article, hn_text: str = "") -> None:
    """Extract body text from article URL and create a summary.

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
        article.summary = "본문을 가져올 수 없습니다."
        return

    sentences = _split_sentences(body)
    if not sentences:
        article.summary = "본문을 가져올 수 없습니다."
        return

    article.summary = _truncate_sentences(sentences)
    logger.info("Summarized '%s': %d chars", article.title, len(article.summary))
