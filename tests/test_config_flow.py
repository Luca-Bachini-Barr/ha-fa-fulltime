"""The search → league → division → team flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.fa_fulltime.api import FullTimeError
from custom_components.fa_fulltime.const import DEFAULT_API_URL, DOMAIN

from .conftest import DIVISION_ID, ENTRY_DATA, LEAGUE, TEAM


async def _start(hass: HomeAssistant):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def test_full_flow(hass: HomeAssistant, api: AsyncMock) -> None:
    """Pick league, division and team; the entry gets their names."""
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"league_query": " Milton Keynes ", "api_url": DEFAULT_API_URL + "/"},
    )
    api.search_leagues.assert_awaited_once_with("Milton Keynes")
    assert result["step_id"] == "league"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"league_id": LEAGUE["id"]}
    )
    assert result["step_id"] == "division"
    assert result["description_placeholders"] == {"league": LEAGUE["name"]}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"division_id": DIVISION_ID}
    )
    assert result["step_id"] == "team"
    api.fixtures.assert_awaited_with(DIVISION_ID)
    api.results.assert_awaited_with(DIVISION_ID)

    with patch("custom_components.fa_fulltime.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"team": TEAM}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == TEAM
    assert result["data"] == ENTRY_DATA
    assert result["result"].unique_id == f"{DIVISION_ID}_{TEAM}"


async def test_single_league_skips_league_step(
    hass: HomeAssistant, api: AsyncMock
) -> None:
    """With one search hit the flow goes straight to divisions."""
    api.search_leagues.return_value = [LEAGUE]
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"league_query": "Development", "api_url": DEFAULT_API_URL}
    )
    assert result["step_id"] == "division"


async def test_cannot_connect_and_no_leagues(
    hass: HomeAssistant, api: AsyncMock
) -> None:
    """Errors on the first step."""
    result = await _start(hass)
    api.search_leagues.side_effect = FullTimeError("down")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"league_query": "x", "api_url": DEFAULT_API_URL}
    )
    assert result["errors"] == {"base": "cannot_connect"}

    api.search_leagues.side_effect = None
    api.search_leagues.return_value = []
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"league_query": "x", "api_url": DEFAULT_API_URL}
    )
    assert result["errors"] == {"league_query": "no_leagues"}


async def test_league_without_divisions(hass: HomeAssistant, api: AsyncMock) -> None:
    """A league with no divisions aborts."""
    api.search_leagues.return_value = [{"id": "1", "name": "Empty", "divisions": []}]
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"league_query": "Empty", "api_url": DEFAULT_API_URL}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_divisions"


async def test_division_errors(hass: HomeAssistant, api: AsyncMock) -> None:
    """The division step reports a dead API and an empty division."""
    api.search_leagues.return_value = [LEAGUE]
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"league_query": "x", "api_url": DEFAULT_API_URL}
    )
    api.results.side_effect = FullTimeError("down")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"division_id": DIVISION_ID}
    )
    assert result["errors"] == {"base": "cannot_connect"}

    api.results.side_effect = None
    api.fixtures.return_value = []
    api.results.return_value = []
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"division_id": DIVISION_ID}
    )
    assert result["errors"] == {"division_id": "no_teams"}


async def test_already_configured(hass: HomeAssistant, api: AsyncMock) -> None:
    """The same team in the same division can't be added twice."""
    MockConfigEntry(
        domain=DOMAIN, data=ENTRY_DATA, unique_id=f"{DIVISION_ID}_{TEAM}"
    ).add_to_hass(hass)
    api.search_leagues.return_value = [LEAGUE]
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"league_query": "x", "api_url": DEFAULT_API_URL}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"division_id": DIVISION_ID}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"team": TEAM}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_team_only_in_results(hass: HomeAssistant, api: AsyncMock) -> None:
    """A team with results but no fixtures left can be picked."""
    api.search_leagues.return_value = [LEAGUE]
    api.fixtures.return_value = []
    api.results.return_value = [
        {
            "fixtureDateTime": "14/11/26 09:00",
            "homeTeam": "Only Results FC",
            "awayTeam": "Other",
            "score": "1 - 0",
        }
    ]
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"league_query": "x", "api_url": DEFAULT_API_URL}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"division_id": DIVISION_ID}
    )
    assert result["step_id"] == "team"
    with patch("custom_components.fa_fulltime.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"team": "Only Results FC"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["team"] == "Only Results FC"
