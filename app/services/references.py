import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.clients.keitaro import KeitaroClient

DEFAULT_ENTITY_NAME = "FORTESTS"


def pick_default_id(items: list[dict[str, Any]]) -> int | None:
    if not items:
        return None
    active = [
        item
        for item in items
        if str(item.get("state") or "active").lower() == "active"
    ]
    pool = active or items
    for item in pool:
        if str(item.get("name") or "").strip().lower() == DEFAULT_ENTITY_NAME.lower():
            return int(item["id"])
    return int(pool[0]["id"])


class ReferenceCache:
    def __init__(self, client: KeitaroClient, ttl: int = 60) -> None:
        self.client = client
        self.ttl = ttl
        self._cache: dict[str, tuple[float, Any]] = {}

    async def _get(
        self, key: str, loader: Callable[[], Awaitable[list[dict[str, Any]]]], force: bool = False
    ) -> list[dict[str, Any]]:
        now = time.monotonic()
        cached = self._cache.get(key)
        if not force and cached and now - cached[0] < self.ttl:
            return cached[1]
        try:
            data = await loader()
        except Exception:
            if cached:
                return cached[1]
            raise
        self._cache[key] = (now, data)
        return data

    async def offers(self, force: bool = False) -> list[dict[str, Any]]:
        return await self._get("offers", self.client.list_offers, force)

    async def domains(self, force: bool = False) -> list[dict[str, Any]]:
        return await self._get("domains", self.client.list_domains, force)

    async def groups(self, force: bool = False) -> list[dict[str, Any]]:
        return await self._get(
            "groups", lambda: self.client.list_groups("campaigns"), force
        )

    async def traffic_sources(self, force: bool = False) -> list[dict[str, Any]]:
        return await self._get(
            "traffic_sources", self.client.list_traffic_sources, force
        )

    async def offer_names(self) -> dict[int, str]:
        offers = await self.offers()
        return {
            int(offer["id"]): str(offer.get("name") or f"Offer #{offer['id']}")
            for offer in offers
            if offer.get("id") is not None
        }
