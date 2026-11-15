"""Polls the FullTime API for one team's division."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import FullTimeClient, FullTimeError
from .const import (
    CONF_DIVISION_ID,
    CONF_SCAN_INTERVAL,
    CONF_TEAM,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    FULLTIME_TZ,
    MATCH_DURATION,
)
from .parse import Match, TeamView, parse_matches, team_view

_LOGGER = logging.getLogger(__name__)
STORAGE_VERSION = 1


@dataclass
class FullTimeData:
    """One poll's worth of data."""

    view: TeamView
    matches: list[Match]
    # Results of this team that appeared since the previous poll, oldest first.
    new_results: list[Match] = field(default_factory=list)


class FullTimeCoordinator(DataUpdateCoordinator[FullTimeData]):
    """Fetch fixtures and results of the division and build the team view."""

    config_entry: ConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: FullTimeClient
    ) -> None:
        """Set up the coordinator with the entry's poll interval."""
        minutes = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=timedelta(minutes=minutes),
        )
        self.client = client
        self.division_id: str = entry.data[CONF_DIVISION_ID]
        self.team: str = entry.data[CONF_TEAM]
        self._tz = dt_util.get_time_zone(FULLTIME_TZ)
        # Results already seen, kept across restarts so a result that came in
        # while HA was down still fires the event once.
        self._store: Store[dict[str, list[str]]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._seen: set[str] | None = None

    async def _async_update_data(self) -> FullTimeData:
        try:
            # One after the other: the API renders each page in one browser tab.
            fixtures = await self.client.fixtures(self.division_id)
            results = await self.client.results(self.division_id)
        except FullTimeError as err:
            raise UpdateFailed(str(err)) from err

        matches = parse_matches(fixtures, results, self._tz)
        if not any(m.involves(self.team) for m in matches):
            raise UpdateFailed(
                f"{self.team} has no matches in division {self.division_id}; "
                "a new season gets new division IDs, so add the team again"
            )
        view = team_view(matches, self.team, dt_util.now(), MATCH_DURATION)
        return FullTimeData(view, matches, await self._new_results(view))

    async def _new_results(self, view: TeamView) -> list[Match]:
        keys = {m.key for m in view.decided}
        if self._seen is None:
            stored = await self._store.async_load()
            if stored is None:
                # First run: everything so far is history, not news.
                self._seen = set(keys)
                await self._store.async_save({"seen": sorted(keys)})
                return []
            self._seen = set(stored.get("seen", []))
        new = [m for m in view.decided if m.key not in self._seen]
        if new:
            self._seen |= keys
            await self._store.async_save({"seen": sorted(self._seen)})
        return new
