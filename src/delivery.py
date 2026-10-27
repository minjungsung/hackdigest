"""Track delivered article fingerprints separately from disposable news caches."""

import hashlib
import html
import json
import os
import re
from base64 import b64decode, b64encode
from pathlib import Path

import requests

from src.fetchers.llm import canonical_url
from src.models import Article, Topic

BRANCH = "hackdigest-delivery-state"


def article_keys(article: Article) -> set[str]:
    """Match canonical links and exact normalized original headlines."""
    title = re.sub(r"[^\w]+", " ", html.unescape(article.original_title or article.title).casefold()).strip()
    values = ["url:" + canonical_url(article.url)]
    if title:
        values.append("title:" + title)
    return {hashlib.sha256(value.encode()).hexdigest() for value in values}


class DeliveryHistory:
    """Store only hashes, with optimistic updates to a dedicated GitHub branch.

    Local execution uses a configurable directory. CI uses the repository's
    authenticated API and fails before sending if history cannot be read.
    Test history is separate from subscriber history.
    """

    def __init__(self, recipient: str):
        recipient_key = hashlib.sha256(recipient.strip().casefold().encode()).hexdigest()
        namespace = "test" if os.environ.get("EMAIL_TEST_TO", "").strip() else "subscribers"
        self.path = f"history/{namespace}/{recipient_key}.json"
        self.repository = os.environ.get("DELIVERY_HISTORY_REPOSITORY", "")
        self.local_path = Path(os.environ.get("DELIVERY_HISTORY_DIR", "data/delivery")) / self.path
        self.sha = None
        self.keys = self._load()

    def _request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        token = os.environ.get("GITHUB_TOKEN", "")
        if not token:
            raise RuntimeError("GitHub delivery history requires authentication")
        return requests.request(method, f"https://api.github.com/repos/{self.repository}/{endpoint}",
                                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                                timeout=30, **kwargs)

    def _load(self) -> set[str]:
        if not self.repository:
            if not self.local_path.exists():
                return set()
            return set(json.loads(self.local_path.read_text(encoding="utf-8")))
        # Verify the repository/branch before treating a missing file as empty.
        branch = self._request("GET", f"git/ref/heads/{BRANCH}")
        if branch.status_code == 404:
            base = self._request("GET", "git/ref/heads/main")
            base.raise_for_status()
            created = self._request("POST", "git/refs", json={"ref": f"refs/heads/{BRANCH}", "sha": base.json()["object"]["sha"]})
            created.raise_for_status()
        else:
            branch.raise_for_status()
        response = self._request("GET", f"contents/{self.path}", params={"ref": BRANCH})
        if response.status_code == 404:
            self.sha = None
            return set()
        response.raise_for_status()
        data = response.json()
        self.sha = data["sha"]
        if data.get("encoding") != "base64":
            blob = self._request("GET", f"git/blobs/{self.sha}")
            blob.raise_for_status()
            data = blob.json()
        keys = json.loads(b64decode(data["content"]))
        if not isinstance(keys, list) or any(not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{64}", key) for key in keys):
            raise RuntimeError("Delivery history is malformed; refusing duplicate-prone delivery")
        return set(keys)

    def record(self, articles: list[Article]) -> None:
        new_keys = set().union(*(article_keys(article) for article in articles))
        self.keys.update(new_keys)
        if not self.repository:
            self.local_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.local_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(sorted(self.keys)), encoding="utf-8")
            temporary.replace(self.local_path)
            return
        for _ in range(3):
            payload = {"message": "Record digest delivery fingerprints [skip ci]", "branch": BRANCH,
                       "content": b64encode(json.dumps(sorted(self.keys)).encode()).decode()}
            if self.sha:
                payload["sha"] = self.sha
            response = self._request("PUT", f"contents/{self.path}", json=payload)
            if response.status_code not in (409, 422):
                response.raise_for_status()
                self.sha = response.json()["content"]["sha"]
                return
            self.keys.update(self._load())
            self.keys.update(new_keys)
        raise RuntimeError("Unable to persist delivery history after concurrent updates")


def select_unseen(articles: list[Article], history: DeliveryHistory, topic: Topic | None) -> list[Article]:
    """Refill unseen Tech items up to five HN stories and ten LLM updates."""
    seen = set(history.keys)
    counts = {}
    selected = []
    for article in articles:
        keys = article_keys(article)
        if keys & seen:
            continue
        section = "llm" if article.section == "llm" else article.topic.value
        limit = 10 if section == "llm" else 5
        if article.topic == Topic.TECH and counts.get(section, 0) >= limit:
            continue
        selected.append(article)
        seen.update(keys)
        counts[section] = counts.get(section, 0) + 1
    return selected
