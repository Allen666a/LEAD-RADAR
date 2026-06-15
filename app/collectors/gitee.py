from __future__ import annotations

from datetime import datetime

import httpx

from app.collectors.base import Collector
from app.schemas import RawItem
from app.settings import get_settings


class GiteeSearchCollector(Collector):
    def __init__(self, query: str, source_name: str | None = None) -> None:
        self.query = query
        self.source_name = source_name or f"Gitee Search: {query}"

    async def collect(self) -> list[RawItem]:
        settings = get_settings()
        params = {
            "q": self.query,
            "page": 1,
            "per_page": 20,
        }
        if settings.gitee_token:
            params["access_token"] = settings.gitee_token

        async with httpx.AsyncClient(
            timeout=20,
            headers={"User-Agent": settings.user_agent},
            follow_redirects=True,
        ) as client:
            response = await client.get("https://gitee.com/api/v5/search/issues", params=params)
            response.raise_for_status()

        items: list[RawItem] = []
        for row in response.json():
            repository = row.get("repository") or {}
            body = row.get("body") or row.get("description") or ""
            items.append(
                RawItem(
                    source_name=self.source_name,
                    source_kind="gitee",
                    title=row.get("title") or "",
                    url=row.get("html_url") or "",
                    author=(row.get("user") or {}).get("login") or "",
                    content="\n".join(
                        part
                        for part in [
                            body,
                            repository.get("full_name") or repository.get("path") or "",
                        ]
                        if part
                    ),
                    published_at=parse_iso(row.get("created_at")),
                )
            )
        return items


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None
