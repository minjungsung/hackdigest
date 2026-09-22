from dataclasses import dataclass


@dataclass
class Article:
    title: str
    url: str
    hn_url: str
    score: int
    comment_count: int
    summary: str = ""
