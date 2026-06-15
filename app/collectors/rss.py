from __future__ import annotations

from datetime import datetime
from email.utils import parsedate_to_datetime

import feedparser
import httpx

from app.collectors.base import Collector
from app.schemas import RawItem
from app.settings import get_settings


class RssCollector(Collector):
    def __init__(self, source_name: str, feed_url: str) -> None:
        self.source_name = source_name
        self.feed_url = feed_url

    async def collect(self) -> list[RawItem]:
        settings = get_settings()
        async with httpx.AsyncClient(
            timeout=20,
            headers={"User-Agent": settings.user_agent},
            follow_redirects=True,
        ) as client:
            response = await client.get(self.feed_url)
            response.raise_for_status()

        parsed = feedparser.parse(response.text)
        items: list[RawItem] = []
        for entry in parsed.entries[:50]:
            published_at = parse_date(
                getattr(entry, "published", None) or getattr(entry, "updated", None)
            )
            items.append(
                RawItem(
                    source_name=self.source_name,
                    source_kind="rss",
                    title=getattr(entry, "title", ""),
                    url=getattr(entry, "link", ""),
                    author=getattr(entry, "author", ""),
                    content=getattr(entry, "summary", ""),
                    published_at=published_at,
                )
            )
        return items


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).replace(tzinfo=None)
    except Exception:  # noqa: BLE001
        return None

