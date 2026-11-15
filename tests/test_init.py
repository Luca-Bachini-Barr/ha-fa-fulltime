"""Setting up the entry: sensors, calendar, result events, failures."""

from __future__ import annotations

import copy
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.fa_fulltime.api import FullTimeError
from custom_components.fa_fulltime.const import CONF_SCAN_INTERVAL, DOMAIN

from .conftest import RESULTS, TEAM

NOW = "2026-11-15 12:00:00+00:00"
P = "wingrave_juniors_u15_wingrave_wasps"


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


@pytest.fixture(autouse=True)
async def _time_zone(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    await hass.config.async_set_time_zone("Europe/London")
    freezer.move_to(NOW)


async def test_sensors(
    hass: HomeAssistant, api: AsyncMock, entry: MockConfigEntry
) -> None:
    """The sensors show the Wasps' season."""
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED

    nxt = hass.states.get(f"sensor.{P}_next_match")
    assert nxt.state == "2026-12-05T09:00:00+00:00"
    assert nxt.attributes["opponent"] == "Real Bedford Wixams U15 Reds"
    assert nxt.attributes["home_away"] == "away"
    assert nxt.attributes["venue"] == "WANDERERS PARK"
    assert len(nxt.attributes["upcoming"]) == 5

    last = hass.states.get(f"sensor.{P}_last_result")
    assert last.state == "win"
    assert last.attributes["score"] == "4–1"
    assert last.attributes["opponent"] == "Padbury Village U15 Cougars"

    pos = hass.states.get(f"sensor.{P}_league_position")
    assert pos.state == "4"
    assert pos.attributes["points"] == 11
    assert pos.attributes["teams"] == 9
    assert pos.attributes["table"][0]["team"] == "Shenley FC U15 Tigers"

    assert hass.states.get(f"sensor.{P}_points").state == "11"
    form = hass.states.get(f"sensor.{P}_form")
    assert form.state == "WDDWW"
    assert [r["outcome"] for r in form.attributes["results"]] == [
        "win",
        "draw",
        "draw",
        "win",
        "win",
    ]

    # No event for results that were already in on the first run.
    assert hass.states.get(f"event.{P}_new_result").state == "unknown"

    reg = er.async_get(hass)
    ent = reg.async_get(f"sensor.{P}_next_match")
    assert ent.unique_id == f"{entry.entry_id}_next_match"


async def test_calendar(
    hass: HomeAssistant, api: AsyncMock, entry: MockConfigEntry
) -> None:
    """Every match of the team, with scores once played."""
    await _setup(hass, entry)
    cal = hass.states.get(f"calendar.{P}_matches")
    assert cal.state == "off"
    assert cal.attributes["message"] == (
        "Real Bedford Wixams U15 Reds v Wingrave Juniors U15 Wingrave Wasps"
    )
    assert cal.attributes["location"] == "WANDERERS PARK"

    result = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": f"calendar.{P}_matches",
            "start_date_time": "2026-09-01 00:00:00",
            "end_date_time": "2026-11-15 00:00:00",
        },
        blocking=True,
        return_response=True,
    )
    events = result[f"calendar.{P}_matches"]["events"]
    assert [e["summary"] for e in events] == [
        "Shenley FC U15 Tigers v Wingrave Juniors U15 Wingrave Wasps (walkover)",
        "Wingrave Juniors U15 Wingrave Wasps 3–2 Real Bedford Wixams U15 Reds",
        "Wingrave Juniors U15 Wingrave Wasps 1–1 Emerson Valley U15 Hurricanes",
        "Hanslope Hornets U15 5–5 Wingrave Juniors U15 Wingrave Wasps",
        "Olney FC U15 Tigers 0–3 Wingrave Juniors U15 Wingrave Wasps",
        "Wingrave Juniors U15 Wingrave Wasps 4–1 Padbury Village U15 Cougars",
    ]
    assert events[3]["description"] == "Away\nDivision 5 U15\nHalf time 1–5"
    assert events[0]["description"].endswith("Home Walkover H - W")


async def test_calendar_postponed_and_all_day(
    hass: HomeAssistant, api: AsyncMock, entry: MockConfigEntry
) -> None:
    """Postponed games are labelled; games without a time are all-day."""
    api.fixtures.return_value = [
        {"fixtureDateTime": "20/11/26", "homeTeam": TEAM, "awayTeam": "X"},
    ]
    api.results.return_value = [
        {
            "fixtureDateTime": "14/11/26 09:00",
            "homeTeam": "Y",
            "awayTeam": TEAM,
            "score": "Postponed P - P",
        }
    ]
    await _setup(hass, entry)
    result = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": f"calendar.{P}_matches",
            "start_date_time": "2026-11-01 00:00:00",
            "end_date_time": "2026-12-01 00:00:00",
        },
        blocking=True,
        return_response=True,
    )
    events = result[f"calendar.{P}_matches"]["events"]
    assert events[0]["summary"] == f"Postponed: Y v {TEAM}"
    assert events[1]["start"] == "2026-11-20"
    assert events[1]["end"] == "2026-11-21"
    state = hass.states.get(f"calendar.{P}_matches")
    assert state.attributes["all_day"] is True
    assert (
        hass.states.get(f"sensor.{P}_next_match").state == "2026-11-20T00:00:00+00:00"
    )


async def test_new_result_fires_event(
    hass: HomeAssistant,
    api: AsyncMock,
    entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A result that appears on a later poll fires the event once."""
    await _setup(hass, entry)
    events = async_capture_events(hass, "state_changed")

    results = copy.deepcopy(RESULTS)
    results.insert(
        0,
        {
            "fixtureDateTime": "05/12/26 09:00",
            "homeTeam": "Real Bedford Wixams U15 Reds",
            "score": "0 - 2 (HT 0-1)",
            "homeScore": "0",
            "awayScore": "2",
            "awayTeam": TEAM,
        },
    )
    api.results.return_value = results
    freezer.tick(timedelta(minutes=121))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    ev = hass.states.get(f"event.{P}_new_result")
    assert ev.attributes["event_type"] == "win"
    assert ev.attributes["score"] == "0–2"
    assert ev.attributes["goals_for"] == 2
    assert ev.attributes["home_away"] == "away"
    assert hass.states.get(f"sensor.{P}_form").state == "DDWWW"
    fired = [e for e in events if e.data["entity_id"] == f"event.{P}_new_result"]
    assert len(fired) == 1

    # Next poll with the same data: no new event.
    freezer.tick(timedelta(minutes=121))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    fired = [e for e in events if e.data["entity_id"] == f"event.{P}_new_result"]
    assert len(fired) == 1


async def test_result_while_down_fires_after_restart(
    hass: HomeAssistant, api: AsyncMock, entry: MockConfigEntry
) -> None:
    """Seen results are stored, so a result found at start-up still fires."""
    await _setup(hass, entry)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    results = copy.deepcopy(RESULTS)
    results.insert(
        0,
        {
            "fixtureDateTime": "05/12/26 09:00",
            "homeTeam": "Real Bedford Wixams U15 Reds",
            "score": "3 - 1",
            "awayTeam": TEAM,
        },
    )
    api.results.return_value = results
    events = async_capture_events(hass, "state_changed")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    ev = hass.states.get(f"event.{P}_new_result")
    assert ev.attributes["event_type"] == "loss"
    fired = [
        e
        for e in events
        if e.data["entity_id"] == f"event.{P}_new_result"
        and e.data["new_state"].state not in ("unknown", "unavailable")
    ]
    assert len(fired) == 1
    assert fired[0].data["new_state"].attributes["opponent"] == (
        "Real Bedford Wixams U15 Reds"
    )


async def test_two_new_results_fire_two_events(
    hass: HomeAssistant,
    api: AsyncMock,
    entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Each new result gets its own event."""
    await _setup(hass, entry)
    events = async_capture_events(hass, "state_changed")
    results = copy.deepcopy(RESULTS)
    for day, score in (("05/12/26", "1 - 1"), ("12/12/26", "0 - 4")):
        results.insert(
            0,
            {
                "fixtureDateTime": f"{day} 09:00",
                "homeTeam": TEAM,
                "awayTeam": "Z",
                "score": score,
            },
        )
    api.results.return_value = results
    freezer.tick(timedelta(minutes=121))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    fired = [
        e.data["new_state"].attributes["event_type"]
        for e in events
        if e.data["entity_id"] == f"event.{P}_new_result"
    ]
    assert fired == ["draw", "loss"]


async def test_setup_retries_when_api_down(
    hass: HomeAssistant, api: AsyncMock, entry: MockConfigEntry
) -> None:
    """The entry retries while the API can't be reached."""
    api.fixtures.side_effect = FullTimeError("boom")
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_team_missing_from_division(
    hass: HomeAssistant, api: AsyncMock, entry: MockConfigEntry
) -> None:
    """A division without the team (new season) is an update failure."""
    api.fixtures.return_value = []
    api.results.return_value = []
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_entities_unavailable_after_failed_poll(
    hass: HomeAssistant,
    api: AsyncMock,
    entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A failed poll marks the entities unavailable until the next good one."""
    await _setup(hass, entry)
    api.results.side_effect = FullTimeError("down")
    freezer.tick(timedelta(minutes=121))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(f"sensor.{P}_points").state == "unavailable"


async def test_options_change_interval_and_reload(
    hass: HomeAssistant, api: AsyncMock, entry: MockConfigEntry
) -> None:
    """Saving options reloads the entry with the new interval."""
    await _setup(hass, entry)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_SCAN_INTERVAL: 45, "api_url": "http://192.168.1.42:5069/"},
    )
    await hass.async_block_till_done()
    assert entry.options == {
        CONF_SCAN_INTERVAL: 45,
        "api_url": "http://192.168.1.42:5069",
    }
    assert entry.runtime_data.update_interval == timedelta(minutes=45)


async def test_remove_entry_deletes_store(
    hass: HomeAssistant, api: AsyncMock, entry: MockConfigEntry, hass_storage
) -> None:
    """Removing the entry deletes its seen-results store."""
    await _setup(hass, entry)
    key = f"{DOMAIN}.{entry.entry_id}"
    assert key in hass_storage
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert key not in hass_storage


async def test_api_url_from_options(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """Options override the setup URL; the default is the public API."""
    from custom_components.fa_fulltime import api_url
    from custom_components.fa_fulltime.const import DEFAULT_API_URL

    assert api_url(entry) == DEFAULT_API_URL
    other = MockConfigEntry(domain=DOMAIN, data={}, options={"api_url": "http://x"})
    assert api_url(other) == "http://x"
    assert api_url(MockConfigEntry(domain=DOMAIN, data={})) == DEFAULT_API_URL


def _new_result(day: str, score: str = "2 - 0") -> dict:
    return {
        "fixtureDateTime": f"{day} 09:00",
        "homeTeam": TEAM,
        "awayTeam": "Z",
        "score": score,
    }


async def _poll(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.tick(timedelta(minutes=121))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_old_unseen_result_does_not_fire(
    hass: HomeAssistant,
    api: AsyncMock,
    entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    hass_storage,
) -> None:
    """A result older than 14 days when first seen is history, not news."""
    await _setup(hass, entry)
    api.results.return_value = [*copy.deepcopy(RESULTS), _new_result("20/10/26")]
    await _poll(hass, freezer)
    assert hass.states.get(f"event.{P}_new_result").state == "unknown"
    seen = hass_storage[f"{DOMAIN}.{entry.entry_id}"]["data"]["seen"]
    assert f"2026-10-20|{TEAM}|Z" in seen


async def test_result_not_seen_until_fired(
    hass: HomeAssistant,
    api: AsyncMock,
    entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    hass_storage,
) -> None:
    """The store only learns a result after the event entity fired it."""
    await _setup(hass, entry)
    key = f"{DOMAIN}.{entry.entry_id}"
    entry.runtime_data.data.new_results = []  # nothing pending
    api.results.return_value = [*copy.deepcopy(RESULTS), _new_result("14/11/26")]
    with patch("custom_components.fa_fulltime.event.FullTimeResultEvent._fire_new"):
        await _poll(hass, freezer)
    assert f"2026-11-14|{TEAM}|Z" not in hass_storage[key]["data"]["seen"]
    # Next poll with the event entity working: fired and stored.
    await _poll(hass, freezer)
    assert hass.states.get(f"event.{P}_new_result").attributes["away_team"] == "Z"
    assert f"2026-11-14|{TEAM}|Z" in hass_storage[key]["data"]["seen"]


async def test_save_merges_with_stored_keys(
    hass: HomeAssistant,
    api: AsyncMock,
    entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    hass_storage,
) -> None:
    """Keys another coordinator of the entry saved are kept."""
    await _setup(hass, entry)
    key = f"{DOMAIN}.{entry.entry_id}"
    hass_storage[key]["data"]["seen"].append("2026-01-01|A|B")
    api.results.return_value = [*copy.deepcopy(RESULTS), _new_result("14/11/26")]
    await _poll(hass, freezer)
    seen = hass_storage[key]["data"]["seen"]
    assert "2026-01-01|A|B" in seen
    assert f"2026-11-14|{TEAM}|Z" in seen


async def test_storage_errors_keep_entities_working(
    hass: HomeAssistant,
    api: AsyncMock,
    entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unreadable or unwritable storage is logged; sensors still update."""

    class BrokenLoad(Store):
        async def async_load(self):
            raise OSError("disk")

    class BrokenSave(Store):
        async def async_save(self, data):
            raise OSError("disk full")

    with patch("custom_components.fa_fulltime.coordinator.Store", BrokenLoad):
        await _setup(hass, entry)
    assert hass.states.get(f"sensor.{P}_points").state == "11"
    assert "Could not read seen results" in caplog.text
    coordinator = entry.runtime_data

    # Storage readable again but empty: after a failed read that is not a
    # first run, so the results of the last 14 days (7 and 14 Nov) fire.
    coordinator._store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")
    events = async_capture_events(hass, "state_changed")
    await _poll(hass, freezer)
    fired = [
        e.data["new_state"].attributes["kickoff"][:10]
        for e in events
        if e.data["entity_id"] == f"event.{P}_new_result"
    ]
    assert fired == ["2026-11-07", "2026-11-14"]

    # Saving fails: the event still fires, the failure is logged.
    coordinator._store = BrokenSave(hass, 1, f"{DOMAIN}.{entry.entry_id}")
    api.results.return_value = [*copy.deepcopy(RESULTS), _new_result("14/11/26")]
    await _poll(hass, freezer)
    assert hass.states.get(f"sensor.{P}_points").state == "14"
    assert hass.states.get(f"event.{P}_new_result").attributes["event_type"] == "win"
    assert "Could not save seen results" in caplog.text
