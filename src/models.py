from dataclasses import dataclass, field
from enum import Enum


class Topic(str, Enum):
    TECH = "tech"
    STOCKS = "stocks"
    REALESTATE = "realestate"


class Language(str, Enum):
    KO = "ko"
    EN = "en"


@dataclass
class Article:
    title: str
    url: str
    hn_url: str
    score: int
    comment_count: int
    topic: Topic = Topic.TECH
    summary: str = ""


@dataclass
class Subscriber:
    email: str
    language: Language = Language.KO
    topics: list[Topic] = field(default_factory=lambda: [Topic.TECH])
