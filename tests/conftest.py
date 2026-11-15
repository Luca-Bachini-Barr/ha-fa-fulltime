"""Fixtures: real Division 5 U15 data (2026-11-15) and a mocked FullTime API."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.fa_fulltime.const import (
    CONF_API_URL,
    CONF_DIVISION_ID,
    CONF_DIVISION_NAME,
    CONF_LEAGUE_ID,
    CONF_LEAGUE_NAME,
    CONF_TEAM,
    DEFAULT_API_URL,
    DOMAIN,
)

PYTEST_PLUGINS = "pytest_homeassistant_custom_component"

HERE = Path(__file__).parent
FIXTURES: list[dict[str, Any]] = json.loads((HERE / "fixtures.json").read_text())
RESULTS: list[dict[str, Any]] = json.loads((HERE / "results.json").read_text())

TEAM = "Wingrave Juniors U15 Wingrave Wasps"
DIVISION_ID = "911905014"
LEAGUE = {
    "id": "96486",
    "name": "The Milton Keynes & District Development League",
    "divisions": [
        {"id": "553061839", "name": "Division 1 U15"},
        {"id": DIVISION_ID, "name": "Division 5 U15"},
    ],
}
OTHER_LEAGUE = {
    "id": "8041368",
    "name": "MILTON KEYNES VETERANS LEAGUE",
    "divisions": [],
}

ENTRY_DATA = {
    CONF_API_URL: DEFAULT_API_URL,
    CONF_LEAGUE_ID: LEAGUE["id"],
    CONF_LEAGUE_NAME: LEAGUE["name"],
    CONF_DIVISION_ID: DIVISION_ID,
    CONF_DIVISION_NAME: "Division 5 U15",
    CONF_TEAM: TEAM,
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load custom integrations in every test."""
    yield


@pytest.fixture
def api() -> AsyncMock:
    """The FullTime API client, as used by the integration and the flow."""
    client = AsyncMock()
    client.base_url = DEFAULT_API_URL
    client.search_leagues.return_value = [LEAGUE, OTHER_LEAGUE]
    client.fixtures.return_value = copy.deepcopy(FIXTURES)
    client.results.return_value = copy.deepcopy(RESULTS)
    with (
        patch("custom_components.fa_fulltime.FullTimeClient", return_value=client),
        patch(
            "custom_components.fa_fulltime.config_flow.FullTimeClient",
            return_value=client,
        ),
    ):
        yield client


@pytest.fixture
def entry() -> MockConfigEntry:
    """A config entry for the Wasps."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=TEAM,
        data=dict(ENTRY_DATA),
        unique_id=f"{DIVISION_ID}_{TEAM}",
    )
