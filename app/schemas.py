from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class RawItem:
    source_name: str
    source_kind: str
    title: str
    url: str
    author: str = ""
    content: str = ""
    published_at: datetime | None = None

