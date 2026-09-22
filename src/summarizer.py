"""Extract and summarize article content."""

import html
import logging
import re

import requests
import trafilatura

from src.models import Article

logger = logging.getLogger(__name__)

TARGET_SENTENCES = 5
MAX_CHARS = 800
MIN_USEFUL_LENGTH = 100  # If extracted text is shorter than this, consider it a failure

HN_API_BASE = "https://hacker-news.firebaseio.com/v0"


def _strip_html(text: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences, filtering out junk."""
    # Split on sentence-ending punctuation
    raw = re.split(r"(?<=[.!?])\s+", text)
    sentences = []
    for s in raw:
        s = s.strip()
        # Skip empty, too short, or likely navigation/boilerplate
        if not s or len(s) < 20:
            continue
        # Skip sentences that are just a title repeat or label
        if s.endswith(":") or s.startswith("Share") or s.startswith("Follow"):
            continue
        sentences.append(s)
    return sentences


def _truncate_sentences(sentences: list[str]) -> str:
    """Select sentences up to TARGET count within character limit."""
    selected = []
    total_chars = 0

    for sent in sentences[:TARGET_SENTENCES]:
        if total_chars + len(sent) > MAX_CHARS and selected:
            break
        selected.append(sent)
        total_chars += len(sent)

    return " ".join(selected)


def _fetch_hn_top_comment(item_id: int) -> str:
    """Fetch the top comment from a HN story as fallback summary."""
    try:
        resp = requests.get(f"{HN_API_BASE}/item/{item_id}.json", timeout=10)
        resp.raise_for_status()
        story = resp.json()
        kids = story.get("kids", [])
        if not kids:
            return ""

        # Get the first (top) comment
        comment_resp = requests.get(f"{HN_API_BASE}/item/{kids[0]}.json", timeout=10)
        comment_resp.raise_for_status()
        comment = comment_resp.json()
        text = comment.get("text", "")
        if text:
            clean = _strip_html(text)
            if len(clean) > MIN_USEFUL_LENGTH:
                # Truncate if too long
                sentences = _split_sentences(clean)
                if sentences:
                    return "[Top HN comment] " + _truncate_sentences(sentences)
                return "[Top HN comment] " + clean[:MAX_CHARS]
    except Exception as e:
        logger.warning("Failed to fetch top comment for item %d: %s", item_id, e)
    return ""


def _extract_item_id(hn_url: str) -> int | None:
    """Extract HN item ID from URL."""
    match = re.search(r"id=(\d+)", hn_url)
    return int(match.group(1)) if match else None


def summarize(article: Article, hn_text: str = "") -> None:
    """Extract body text from article URL and create a summary.

    If extraction fails or produces too little text, falls back to the top HN comment.
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
                # Try with different settings for better extraction
                extracted = trafilatura.extract(
                    downloaded,
                    include_comments=False,
                    include_tables=False,
                    no_fallback=False,
                )
                if extracted:
                    body = extracted
        except Exception as e:
            logger.warning("Failed to extract content from %s: %s", article.url, e)

    # Check if we got enough useful content
    if body and len(body) >= MIN_USEFUL_LENGTH:
        sentences = _split_sentences(body)
        if sentences:
            article.summary = _truncate_sentences(sentences)
            logger.info("Summarized '%s': %d chars", article.title, len(article.summary))
            return

    # Fallback: use top HN comment as summary
    logger.info("Content extraction insufficient for '%s', trying top HN comment...", article.title)
    item_id = _extract_item_id(article.hn_url)
    if item_id:
        comment_summary = _fetch_hn_top_comment(item_id)
        if comment_summary:
            article.summary = comment_summary
            logger.info("Used top comment for '%s': %d chars", article.title, len(article.summary))
            return

    article.summary = "No summary available — click the link to read the full article."
    logger.warning("No summary available for '%s'", article.title)
