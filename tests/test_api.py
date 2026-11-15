"""The FullTime API client."""

from __future__ import annotations

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.fa_fulltime.api import FullTimeClient, FullTimeError

BASE = "https://api.example"


async def test_search_leagues(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Names are unescaped, bad rows dropped, the query URL-encoded."""
    aioclient_mock.get(
        f"{BASE}/api/Search/leagues/Milton%20Keynes%20%26%20District",
        json=[
            {
                "id": "96486",
                "name": "The Milton Keynes &amp; District Development League",
                "divisions": [{"id": 1, "name": "U15 &amp; under"}, {"name": "no id"}],
            },
            {"name": "no id"},
            "junk",
            {"id": "2", "name": "Other", "divisions": None},
        ],
    )
    client = FullTimeClient(async_get_clientsession(hass), BASE + "/")
    assert client.base_url == BASE
    assert await client.search_leagues("Milton Keynes & District") == [
        {
            "id": "96486",
            "name": "The Milton Keynes & District Development League",
            "divisions": [{"id": "1", "name": "U15 & under"}],
        },
        {"id": "2", "name": "Other", "divisions": []},
    ]


async def test_fixtures_and_results(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Lists come back with non-dict items dropped."""
    aioclient_mock.get(f"{BASE}/api/Fixtures/911", json=[{"a": 1}, 3])
    aioclient_mock.get(f"{BASE}/api/Results/911", text='[{"b": 2}]')
    client = FullTimeClient(async_get_clientsession(hass), BASE)
    assert await client.fixtures("911") == [{"a": 1}]
    assert await client.results("911") == [{"b": 2}]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"status": 500},
        {"exc": aiohttp.ClientError()},
        {"exc": TimeoutError()},
        {"text": "<html>not json"},
        {"json": {"not": "a list"}},
    ],
)
async def test_errors(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, kwargs
) -> None:
    """HTTP errors, timeouts, bad JSON and wrong shapes raise FullTimeError."""
    aioclient_mock.get(f"{BASE}/api/Results/1", **kwargs)
    aioclient_mock.get(f"{BASE}/api/Search/leagues/x", **kwargs)
    client = FullTimeClient(async_get_clientsession(hass), BASE)
    with pytest.raises(FullTimeError):
        await client.results("1")
    with pytest.raises(FullTimeError):
        await client.search_leagues("x")
