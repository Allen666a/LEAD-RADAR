from __future__ import annotations

from datetime import datetime

import httpx

from app.collectors.base import Collector
from app.schemas import RawItem
from app.settings import get_settings


class V2exLatestCollector(Collector):
    def __init__(self, source_name: str = "V2EX Latest") -> None:
        self.source_name = source_name

    async def collect(self) -> list[RawItem]:
        return await collect_v2ex_api(
            "https://www.v2ex.com/api/topics/latest.json",
            self.source_name,
        )


class V2exHotCollector(Collector):
    def __init__(self, source_name: str = "V2EX Hot") -> None:
        self.source_name = source_name

    async def collect(self) -> list[RawItem]:
        return await collect_v2ex_api(
            "https://www.v2ex.com/api/topics/hot.json",
            self.source_name,
        )


class V2exNodeCollector(Collector):
    def __init__(self, node_name: str, source_name: str | None = None) -> None:
        self.node_name = node_name
        self.source_name = source_name or f"V2EX Node: {node_name}"

    async def collect(self) -> list[RawItem]:
        return await collect_v2ex_api(
            f"https://www.v2ex.com/api/topics/show.json?node_name={self.node_name}",
            self.source_name,
        )


async def collect_v2ex_api(url: str, source_name: str) -> list[RawItem]:
        settings = get_settings()
        async with httpx.AsyncClient(
            timeout=20,
            headers={"User-Agent": settings.user_agent},
            follow_redirects=True,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

        items: list[RawItem] = []
        for row in response.json()[:100]:
            topic_id = row.get("id")
            items.append(
                RawItem(
                    source_name=source_name,
                    source_kind="v2ex",
                    title=row.get("title") or "",
                    url=f"https://www.v2ex.com/t/{topic_id}" if topic_id else row.get("url", ""),
                    author=(row.get("member") or {}).get("username") or "",
                    content=row.get("content") or "",
                    published_at=parse_timestamp(row.get("created")),
                )
            )
        return items


def parse_timestamp(value: int | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value))
    except Exception:  # noqa: BLE001
        return None
