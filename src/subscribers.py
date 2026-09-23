"""Subscriber management: load/save subscribers from JSON file."""

import json
import logging
from pathlib import Path

from src.models import Language, Subscriber, Topic

logger = logging.getLogger(__name__)

DEFAULT_SUBSCRIBERS_PATH = Path(__file__).parent.parent / "subscribers.json"


def load_subscribers(path: Path = DEFAULT_SUBSCRIBERS_PATH) -> list[Subscriber]:
    """Load subscribers from JSON file."""
    if not path.exists():
        logger.warning("Subscribers file not found: %s", path)
        return []

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    subscribers = []
    for entry in data:
        try:
            sub = Subscriber(
                email=entry["email"],
                language=Language(entry.get("language", "ko")),
                topics=[Topic(t) for t in entry.get("topics", ["tech"])],
            )
            subscribers.append(sub)
        except (KeyError, ValueError) as e:
            logger.warning("Invalid subscriber entry %s: %s", entry, e)

    logger.info("Loaded %d subscriber(s) from %s", len(subscribers), path)
    return subscribers


def save_subscribers(subscribers: list[Subscriber], path: Path = DEFAULT_SUBSCRIBERS_PATH) -> None:
    """Save subscribers to JSON file."""
    data = [
        {
            "email": sub.email,
            "language": sub.language.value,
            "topics": [t.value for t in sub.topics],
        }
        for sub in subscribers
    ]

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    logger.info("Saved %d subscriber(s) to %s", len(subscribers), path)


def add_subscriber(
    email: str,
    language: str = "ko",
    topics: str = "tech",
    path: Path = DEFAULT_SUBSCRIBERS_PATH,
) -> str:
    """Add a subscriber. Returns status message."""
    subscribers = load_subscribers(path)

    # Check duplicate
    if any(s.email.lower() == email.lower() for s in subscribers):
        return f"⚠️ {email} is already subscribed"

    # Parse topics
    topic_list = []
    for t in topics.split(","):
        t = t.strip().lower()
        try:
            topic_list.append(Topic(t))
        except ValueError:
            return f"❌ Invalid topic: {t}. Valid: {', '.join(v.value for v in Topic)}"

    if not topic_list:
        topic_list = [Topic.TECH]

    # Parse language
    try:
        lang = Language(language.strip().lower())
    except ValueError:
        return f"❌ Invalid language: {language}. Valid: {', '.join(v.value for v in Language)}"

    sub = Subscriber(email=email, language=lang, topics=topic_list)
    subscribers.append(sub)
    save_subscribers(subscribers, path)
    return f"✅ Added {email} (lang={lang.value}, topics={','.join(t.value for t in topic_list)})"


def remove_subscriber(email: str, path: Path = DEFAULT_SUBSCRIBERS_PATH) -> str:
    """Remove a subscriber by email. Returns status message."""
    subscribers = load_subscribers(path)
    original_count = len(subscribers)
    subscribers = [s for s in subscribers if s.email.lower() != email.lower()]

    if len(subscribers) == original_count:
        return f"⚠️ {email} was not found"

    save_subscribers(subscribers, path)
    return f"🗑️ Removed {email}"


def update_subscriber(
    email: str,
    language: str | None = None,
    topics: str | None = None,
    path: Path = DEFAULT_SUBSCRIBERS_PATH,
) -> str:
    """Update a subscriber's language or topics. Returns status message."""
    subscribers = load_subscribers(path)

    target = None
    for s in subscribers:
        if s.email.lower() == email.lower():
            target = s
            break

    if not target:
        return f"⚠️ {email} was not found"

    if language:
        try:
            target.language = Language(language.strip().lower())
        except ValueError:
            return f"❌ Invalid language: {language}. Valid: {', '.join(v.value for v in Language)}"

    if topics:
        topic_list = []
        for t in topics.split(","):
            t = t.strip().lower()
            try:
                topic_list.append(Topic(t))
            except ValueError:
                return f"❌ Invalid topic: {t}. Valid: {', '.join(v.value for v in Topic)}"
        target.topics = topic_list

    save_subscribers(subscribers, path)
    return f"✅ Updated {email} (lang={target.language.value}, topics={','.join(t.value for t in target.topics)})"
