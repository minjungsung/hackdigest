"""HackDigest - Hacker News Daily Top 5 digest service."""

import copy
import logging
import os
import sys

from src.cache import load_articles, load_summaries, save_articles, save_summaries, has_cache
from src.fetchers import fetch_articles_by_topic, LANGUAGE_DEPENDENT_TOPICS
from src.models import Article, Language, Subscriber, Topic
from src.notifier import send_email_to_subscriber
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
            Subscriber(email=test_email, language=Language.KO, topics=[Topic.TECH, Topic.STOCKS, Topic.REALESTATE]),
        ]

    if not subscribers:
        logger.warning("No subscribers found. Nothing to do.")
        return

    # 2. Collect all unique (topic, language) combos needed
    all_topic_lang_combos: set[tuple[Topic, Language]] = set()
    for sub in subscribers:
        for topic in sub.topics:
            if topic in LANGUAGE_DEPENDENT_TOPICS:
                # Language-dependent: each language gets different articles
                all_topic_lang_combos.add((topic, sub.language))
            else:
                # Language-independent: same articles for all languages
                # Use all languages that need this topic
                all_topic_lang_combos.add((topic, sub.language))

    logger.info("Topic-language combos needed: %s",
                [(t.value, l.value) for t, l in all_topic_lang_combos])

    # 3. Fetch articles per (topic, language) combo
    #    For language-independent topics, fetch once and share across languages.
    articles_by_combo: dict[tuple[Topic, Language], list[Article]] = {}
    fetched_topics: dict[Topic, list[Article]] = {}  # cache for language-independent topics

    for topic, language in all_topic_lang_combos:
        if topic in LANGUAGE_DEPENDENT_TOPICS:
            # Language-dependent: fetch separately per language
            cached = load_articles(topic)
            # Check if cached articles match the language by looking at URLs
            # For language-dependent topics, skip shared cache — always fetch per language
            fetched = fetch_articles_by_topic(topic, language=language)
            if fetched:
                articles_by_combo[(topic, language)] = fetched
                logger.info("Fetched %d %s articles for (%s, %s)",
                            len(fetched), topic.value, topic.value, language.value)
            else:
                logger.warning("No articles found for (%s, %s)", topic.value, language.value)
                articles_by_combo[(topic, language)] = []
        else:
            # Language-independent: fetch once, reuse
            if topic not in fetched_topics:
                cached = load_articles(topic)
                if cached:
                    logger.info("Using cached articles for topic '%s' (%d articles)",
                                topic.value, len(cached))
                    fetched_topics[topic] = cached
                else:
                    fetched = fetch_articles_by_topic(topic)
                    if fetched:
                        fetched_topics[topic] = fetched
                        logger.info("Fetched %d articles for topic '%s'",
                                    len(fetched), topic.value)
                    else:
                        logger.warning("No articles found for topic '%s'", topic.value)
                        fetched_topics[topic] = []

            articles_by_combo[(topic, language)] = fetched_topics[topic]

    # 4. For each (topic, language) combo: generate summaries
    for (topic, language), articles in articles_by_combo.items():
        if not articles:
            continue

        cached_summaries = load_summaries(language)
        need_summarize = [a for a in articles if a.url not in cached_summaries]

        if not need_summarize:
            logger.info("All summaries cached for (%s, %s)", topic.value, language.value)
            continue

        logger.info("Summarizing %d articles for (%s, %s)...",
                     len(need_summarize), topic.value, language.value)
        summarized_articles = []
        for a in need_summarize:
            temp = copy.deepcopy(a)
            temp.summary = ""
            summarize(temp, language=language)
            summarized_articles.append(temp)

        # Merge into cache
        all_for_cache = []
        for a in articles:
            if a.url in cached_summaries:
                cached_copy = copy.deepcopy(a)
                cached_entry = cached_summaries[a.url]
                cached_copy.title = cached_entry.get("title", a.title)
                cached_copy.summary = cached_entry.get("summary", "")
                all_for_cache.append(cached_copy)
            else:
                match = next((s for s in summarized_articles if s.url == a.url), None)
                if match:
                    all_for_cache.append(match)

        save_summaries(all_for_cache, language)

    # 5. Save articles to cache
    saved_topics: set[Topic] = set()
    for (topic, language), articles in articles_by_combo.items():
        if articles and topic not in saved_topics:
            save_articles(articles, topic)
            saved_topics.add(topic)

    # 6. Send emails
    email_from = os.environ.get("EMAIL_FROM", "")
    email_password = os.environ.get("EMAIL_APP_PASSWORD", "")

    if not email_from or not email_password:
        logger.error("EMAIL_FROM and EMAIL_APP_PASSWORD must be set.")
        sys.exit(1)

    sent_count = 0
    # Pre-load summaries per language
    summaries_cache: dict[Language, dict[str, dict]] = {}
    for lang in {sub.language for sub in subscribers}:
        summaries_cache[lang] = load_summaries(lang)

    # Open one SMTP connection for all emails
    import smtplib
    smtp_server = None
    try:
        try:
            smtp_server = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30)
            smtp_server.login(email_from, email_password)
        except Exception as ssl_err:
            logger.warning("SMTP_SSL failed: %s. Trying STARTTLS...", ssl_err)
            smtp_server = smtplib.SMTP("smtp.gmail.com", 587, timeout=30)
            smtp_server.starttls()
            smtp_server.login(email_from, email_password)

        for sub in subscribers:
            for topic in sub.topics:
                topic_articles = articles_by_combo.get((topic, sub.language), [])
                if not topic_articles:
                    logger.info("No articles for subscriber %s topic %s, skipping.",
                                sub.email, topic.value)
                    continue

                cached_summaries = summaries_cache.get(sub.language, {})
                sub_articles = []
                for a in topic_articles:
                    cached = cached_summaries.get(a.url, {})
                    article_copy = Article(
                        title=cached.get("title", a.title),
                        url=a.url,
                        hn_url=a.hn_url,
                        score=a.score,
                        comment_count=a.comment_count,
                        topic=a.topic,
                        summary=cached.get("summary", ""),
                    )
                    sub_articles.append(article_copy)

                try:
                    send_email_to_subscriber(
                        sub_articles, sub, email_from, email_password,
                        topic=topic, smtp_server=smtp_server,
                    )
                    sent_count += 1
                except Exception as e:
                    logger.error("Failed to send %s email to %s: %s",
                                 topic.value, sub.email, e)

    finally:
        if smtp_server:
            try:
                smtp_server.quit()
            except Exception:
                pass

    if sent_count == 0:
        logger.error("No emails sent successfully.")
        sys.exit(1)

    logger.info("Done! Sent %d email(s) to %d subscriber(s).", sent_count, len(subscribers))


if __name__ == "__main__":
    main()
