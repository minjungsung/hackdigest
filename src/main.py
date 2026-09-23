"""HackDigest - Hacker News Daily Top 5 digest service."""

import logging
import os
import sys

from src.cache import load_articles, load_summaries, save_articles, save_summaries, has_cache
from src.fetcher import fetch_articles_by_topic
from src.models import Article, Language, Subscriber, Topic
from src.notifier import send_email_to_subscriber, send_to_teams
from src.subscribers import load_subscribers
from src.summarizer import summarize

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    # 1. Load subscribers
    subscribers = load_subscribers()

    # Test mode: override subscribers with a single test email
    test_email = os.environ.get("EMAIL_TEST_TO", "").strip()
    if test_email:
        logger.info("Test mode: overriding subscribers with %s", test_email)
        subscribers = [
            Subscriber(email=test_email, language=Language.KO, topics=[Topic.TECH]),
        ]

    if not subscribers:
        logger.warning("No subscribers found. Nothing to do.")
        return

    # 2. Collect all unique topics needed across subscribers
    all_topics: set[Topic] = set()
    for sub in subscribers:
        all_topics.update(sub.topics)
    logger.info("Topics needed: %s", [t.value for t in all_topics])

    # 3. For each topic: fetch articles (or load from cache if available today)
    articles_by_topic: dict[Topic, list[Article]] = {}
    for topic in all_topics:
        cached = load_articles(topic)
        if cached:
            logger.info("Using cached articles for topic '%s' (%d articles)", topic.value, len(cached))
            articles_by_topic[topic] = cached
        else:
            fetched = fetch_articles_by_topic(topic)
            if fetched:
                articles_by_topic[topic] = fetched
                logger.info("Fetched %d articles for topic '%s'", len(fetched), topic.value)
            else:
                logger.warning("No articles found for topic '%s'", topic.value)
                articles_by_topic[topic] = []

    # 4. For each unique (topic, language) combo: summarize articles
    all_topic_lang_combos: set[tuple[Topic, Language]] = set()
    for sub in subscribers:
        for topic in sub.topics:
            all_topic_lang_combos.add((topic, sub.language))

    for topic, language in all_topic_lang_combos:
        articles = articles_by_topic.get(topic, [])
        if not articles:
            continue

        # Check if summaries are already cached for this language
        cached_summaries = load_summaries(language)
        all_summarized = all(a.url in cached_summaries for a in articles)

        if all_summarized:
            # Apply cached summaries to articles
            for a in articles:
                if a.url in cached_summaries:
                    a.summary = cached_summaries[a.url].get("summary", "")
            logger.info("Using cached summaries for (%s, %s)", topic.value, language.value)
        else:
            # Summarize articles that don't have cached summaries
            for a in articles:
                if a.url in cached_summaries:
                    a.summary = cached_summaries[a.url].get("summary", "")
                else:
                    summarize(a, language=language)

            # Save summaries to cache
            save_summaries(articles, language)

    # 5. Save articles to cache (with summaries attached)
    for topic, articles in articles_by_topic.items():
        if articles:
            save_articles(articles, topic)

    # 6. For each subscriber: send personalized email
    email_from = os.environ.get("EMAIL_FROM", "")
    email_password = os.environ.get("EMAIL_APP_PASSWORD", "")
    webhook_url = os.environ.get("TEAMS_WEBHOOK_URL", "")

    if not email_from or not email_password:
        logger.error("EMAIL_FROM and EMAIL_APP_PASSWORD must be set.")
        sys.exit(1)

    # Build a flat list of all articles for Teams (all topics combined)
    all_articles: list[Article] = []
    for articles in articles_by_topic.values():
        all_articles.extend(articles)

    sent_count = 0
    for sub in subscribers:
        # Collect articles for this subscriber's topics, applying correct language summaries
        sub_articles: list[Article] = []
        for topic in sub.topics:
            topic_articles = articles_by_topic.get(topic, [])
            if not topic_articles:
                continue

            # Load the correct language summaries for this subscriber
            cached_summaries = load_summaries(sub.language)
            for a in topic_articles:
                # Create a copy so we don't mutate shared article objects
                article_copy = Article(
                    title=a.title,
                    url=a.url,
                    hn_url=a.hn_url,
                    score=a.score,
                    comment_count=a.comment_count,
                    topic=a.topic,
                    summary=cached_summaries.get(a.url, {}).get("summary", a.summary),
                )
                sub_articles.append(article_copy)

        if not sub_articles:
            logger.info("No articles for subscriber %s, skipping.", sub.email)
            continue

        try:
            send_email_to_subscriber(sub_articles, sub, email_from, email_password)
            sent_count += 1
        except Exception as e:
            logger.error("Failed to send email to %s: %s", sub.email, e)

    # Send Teams notification (optional, uses all articles with default language)
    if webhook_url and all_articles:
        try:
            send_to_teams(all_articles, webhook_url)
        except Exception as e:
            logger.error("Failed to send Teams notification: %s", e)

    if sent_count == 0:
        logger.error("No emails sent successfully.")
        sys.exit(1)

    logger.info("Done! Sent digest to %d/%d subscriber(s).", sent_count, len(subscribers))


if __name__ == "__main__":
    main()
