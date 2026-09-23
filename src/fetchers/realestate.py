"""Fetch real estate news. Placeholder — source not yet configured."""

import logging

from src.models import Article

logger = logging.getLogger(__name__)


def fetch_realestate_articles(count: int = 5) -> list[Article]:
    """Fetch real estate articles. Placeholder — not yet configured."""
    logger.info("Realestate source not configured yet")
    return []
