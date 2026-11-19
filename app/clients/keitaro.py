import asyncio
import json
from typing import Any

import httpx

from app.config import settings


class KeitaroAPIError(Exception):
    def __init__(
        self,
        status_code: int,
        detail: str,
        payload: Any = None,
        method: str | None = None,
        path: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.detail = detail
        self.payload = payload
        self.method = method
        self.path = path
        super().__init__(f"Keitaro API error {status_code}: {detail}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "detail": self.detail,
            "keitaro_status": self.status_code,
            "method": self.method,
            "path": self.path,
            "payload": self.payload,
        }


class KeitaroClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = (base_url or settings.keitaro_base_url).rstrip("/")
        headers = dict(settings.keitaro_headers)
        if api_key is not None:
            headers["Api-Key"] = api_key
        if not headers["Api-Key"]:
            raise ValueError("KEITARO_API_KEY is not configured")
        self._client = httpx.AsyncClient(
            headers=headers,
            timeout=timeout or settings.http_timeout,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "KeitaroClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    def _url(self, path: str) -> str:
        return f"{self._base_url}/{path.lstrip('/')}"

    @staticmethod
    def _extract_error(response: httpx.Response) -> str:
        text = response.text.strip()
        try:
            data = response.json()
        except ValueError:
            return text[:1500] or f"HTTP {response.status_code}"
        if isinstance(data, dict):
            for key in ("error", "name", "message", "detail"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            errors = data.get("errors")
            if errors:
                return json.dumps(errors, ensure_ascii=False)[:1500]
            return json.dumps(data, ensure_ascii=False)[:1500]
        if isinstance(data, list):
            return json.dumps(data, ensure_ascii=False)[:1500]
        return str(data)[:1500]

    async def _request(
        self,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        attempts = 2 if method == "GET" else 1
        response: httpx.Response | None = None
        for attempt in range(attempts):
            try:
                response = await self._client.request(
                    method, self._url(path), json=json_body, params=params
                )
                break
            except httpx.HTTPError as exc:
                if attempt + 1 < attempts:
                    await asyncio.sleep(1)
                    continue
                raise KeitaroAPIError(
                    502,
                    f"Keitaro connection error ({exc.__class__.__name__}) on {method} {path}",
                    method=method,
                    path=path,
                ) from exc
        if response is None:
            raise KeitaroAPIError(502, "Keitaro returned no response", method=method, path=path)

        if response.status_code >= 400:
            payload: Any = None
            try:
                payload = response.json()
            except ValueError:
                payload = response.text[:1500]
            raise KeitaroAPIError(
                response.status_code,
                self._extract_error(response),
                payload=payload,
                method=method,
                path=path,
            )

        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return response.text

    async def list_campaigns(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/campaigns")
        return data if isinstance(data, list) else []

    async def get_campaign(self, campaign_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/campaigns/{campaign_id}")

    async def create_campaign(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/campaigns", json_body=payload)

    async def archive_campaign(self, campaign_id: int) -> Any:
        return await self._request("DELETE", f"/campaigns/{campaign_id}")

    async def list_streams(self, campaign_id: int) -> list[dict[str, Any]]:
        data = await self._request("GET", f"/campaigns/{campaign_id}/streams")
        return data if isinstance(data, list) else []

    async def get_stream(self, stream_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/streams/{stream_id}")

    async def create_stream(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/streams", json_body=payload)

    async def update_stream(self, stream_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("PUT", f"/streams/{stream_id}", json_body=payload)

    async def list_offers(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/offers")
        return data if isinstance(data, list) else []

    async def get_offer(self, offer_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/offers/{offer_id}")

    async def create_offer(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/offers", json_body=payload)

    async def archive_offer(self, offer_id: int) -> Any:
        return await self._request("DELETE", f"/offers/{offer_id}/archive")

    async def list_domains(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/domains")
        return data if isinstance(data, list) else []

    async def list_groups(self, group_type: str = "campaigns") -> list[dict[str, Any]]:
        data = await self._request("GET", "/groups", params={"type": group_type})
        return data if isinstance(data, list) else []

    async def list_traffic_sources(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/traffic_sources")
        return data if isinstance(data, list) else []

    async def list_stream_filters(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/stream_filters")
        return data if isinstance(data, list) else []

    async def list_stream_actions(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/streams_actions")
        return data if isinstance(data, list) else []
