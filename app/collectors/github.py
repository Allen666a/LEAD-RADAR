from __future__ import annotations

from datetime import datetime

import httpx

from app.collectors.base import Collector
from app.schemas import RawItem
from app.settings import get_settings


class GitHubSearchCollector(Collector):
    def __init__(self, query: str, source_name: str | None = None) -> None:
        self.query = query
        self.source_name = source_name or f"GitHub Search: {query}"

    async def collect(self) -> list[RawItem]:
        settings = get_settings()
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": settings.user_agent,
        }
        if settings.github_token:
            headers["Authorization"] = f"Bearer {settings.github_token}"

        query = build_issue_query(self.query)
        params = {
            "q": query,
            "sort": "updated",
            "order": "desc",
            "per_page": 20,
        }

        async with httpx.AsyncClient(timeout=20, headers=headers) as client:
            response = await client.get("https://api.github.com/search/issues", params=params)
            response.raise_for_status()

        payload = response.json()
        items: list[RawItem] = []
        for row in payload.get("items", []):
            if row.get("pull_request"):
                continue
            items.append(
                RawItem(
                    source_name=self.source_name,
                    source_kind="github",
                    title=row.get("title") or "",
                    url=row.get("html_url") or "",
                    author=(row.get("user") or {}).get("login") or "",
                    content=row.get("body") or "",
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


def build_issue_query(query: str) -> str:
    cleaned = " ".join((query or "").split())
    if not cleaned:
        return "residential proxy in:title,body created:>=2026-01-01"
    qualifier_terms = ("repo:", "user:", "org:", "language:", "label:", "state:", "created:", "updated:", "is:")
    has_qualifier = any(term in cleaned for term in qualifier_terms)
    has_quotes = '"' in cleaned
    if has_qualifier or has_quotes:
        built = f"{cleaned} in:title,body"
    else:
        built = f'"{cleaned}" in:title,body'
    if "created:" not in built and "updated:" not in built:
        built = f"{built} created:>=2026-01-01"
    return built
