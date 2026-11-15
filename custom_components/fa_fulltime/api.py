"""Client for the FullTime API (JSON over FA Full-Time)."""

from __future__ import annotations

import html
import json
from typing import Any
from urllib.parse import quote

import aiohttp
from yarl import URL

from .const import MAX_RESPONSE_BYTES, REQUEST_TIMEOUT


class FullTimeError(Exception):
    """The FullTime API could not be reached or answered badly."""


class FullTimeClient:
    """Read leagues, divisions, fixtures and results from a FullTime API."""

    def __init__(self, session: aiohttp.ClientSession, base_url: str) -> None:
        """Store the session and the API's base URL."""
        self._session = session
        self.base_url = base_url.rstrip("/")

    async def _get(self, path: str) -> Any:
        url = f"{self.base_url}/api/{path}"
        # Errors end up in the log: never show credentials in the URL.
        shown = str(URL(url).with_user(None))
        try:
            async with self._session.get(
                url, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
            ) as resp:
                if resp.status != 200:
                    raise FullTimeError(f"GET {shown}: HTTP {resp.status}")
                body = await resp.content.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise FullTimeError(
                        f"GET {shown}: response over {MAX_RESPONSE_BYTES} bytes"
                    )
                return json.loads(body)
        except (TimeoutError, aiohttp.ClientError, ValueError) as err:
            raise FullTimeError(f"GET {shown}: {type(err).__name__}") from err

    async def search_leagues(self, name: str) -> list[dict[str, Any]]:
        """Leagues whose name contains `name`, each with its divisions.

        Returns [{"id", "name", "divisions": [{"id", "name"}]}], names unescaped.
        """
        data = await self._get(f"Search/leagues/{quote(name, safe='')}")
        if not isinstance(data, list):
            raise FullTimeError("League search did not return a list")
        leagues = []
        for league in data:
            if not isinstance(league, dict) or not league.get("id"):
                continue
            leagues.append(
                {
                    "id": str(league["id"]),
                    "name": html.unescape(str(league.get("name", ""))),
                    "divisions": [
                        {
                            "id": str(div["id"]),
                            "name": html.unescape(str(div.get("name", ""))),
                        }
                        for div in league.get("divisions") or []
                        if isinstance(div, dict) and div.get("id")
                    ],
                }
            )
        return leagues

    async def fixtures(self, division_id: str) -> list[dict[str, Any]]:
        """Upcoming (and not yet played) fixtures of a division."""
        return await self._list(f"Fixtures/{quote(division_id, safe='')}")

    async def results(self, division_id: str) -> list[dict[str, Any]]:
        """Results (played, postponed, walkovers) of a division."""
        return await self._list(f"Results/{quote(division_id, safe='')}")

    async def _list(self, path: str) -> list[dict[str, Any]]:
        data = await self._get(path)
        if not isinstance(data, list):
            raise FullTimeError(f"{path} did not return a list")
        return [item for item in data if isinstance(item, dict)]
