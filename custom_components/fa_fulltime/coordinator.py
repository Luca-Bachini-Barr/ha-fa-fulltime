"""Polls the FullTime API for one team's division."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
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
    RESULT_EVENT_MAX_AGE,
    RETRY_INTERVAL,
    STALE_DATA_MAX_AGE,
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
        self._normal_interval = timedelta(minutes=minutes)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=self._normal_interval,
        )
        # When the last poll that reached the API succeeded.
        self._last_success: datetime | None = None
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
        self._load_failed = False
        # One lock per entry, shared with the coordinator of a reloaded entry,
        # so reads and saves of the store never interleave.
        locks: dict[str, asyncio.Lock] = hass.data.setdefault(DOMAIN, {})
        self._lock = locks.setdefault(entry.entry_id, asyncio.Lock())

    async def _async_update_data(self) -> FullTimeData:
        try:
            # One after the other: the API renders each page in one browser tab.
            fixtures = await self.client.fixtures(self.division_id)
            results = await self.client.results(self.division_id)
        except FullTimeError as err:
            return self._stale_data(err)
        matches = parse_matches(fixtures, results, self._tz)
        if not any(m.involves(self.team) for m in matches):
            raise UpdateFailed(
                f"{self.team} has no matches in division {self.division_id}; "
                "a new season gets new division IDs, so add the team again"
            )
        # Only usable data counts as a success for the outage fallback.
        self._last_success = dt_util.utcnow()
        if self.update_interval != self._normal_interval:
            _LOGGER.info("FullTime API is back for %s", self.team)
            self.update_interval = self._normal_interval
        view = team_view(matches, self.team, dt_util.now(), MATCH_DURATION)
        return FullTimeData(view, matches, await self._new_results(view))

    def _stale_data(self, err: FullTimeError) -> FullTimeData:
        """Keep the last good data through a short API outage.

        The team view is worked out again so the next match and the calendar
        move on with the clock. No new-result events fire from old data.
        Raises UpdateFailed when there is no data yet or it is too old.
        """
        # Poll again soon, but never less often than the configured interval.
        self.update_interval = min(RETRY_INTERVAL, self._normal_interval)
        if (
            self.data is None
            or self._last_success is None
            or dt_util.utcnow() - self._last_success > STALE_DATA_MAX_AGE
        ):
            raise UpdateFailed(str(err)) from err
        _LOGGER.warning(
            "%s; keeping data from %s, retrying in %s",
            err,
            dt_util.as_local(self._last_success).isoformat(timespec="minutes"),
            self.update_interval,
        )
        matches = self.data.matches
        view = team_view(matches, self.team, dt_util.now(), MATCH_DURATION)
        return FullTimeData(view, matches)

    async def _new_results(self, view: TeamView) -> list[Match]:
        """Results of the team not yet reported, oldest first.

        They are only marked as seen once the event entity has fired them
        (see `mark_seen`), so a crash in between reports them again rather
        than never.
        """
        if self._seen is None:
            try:
                async with self._lock:
                    stored = await self._store.async_load()
            except (HomeAssistantError, OSError, ValueError) as err:
                _LOGGER.warning("Could not read seen results, retrying: %s", err)
                self._load_failed = True
                return []
            if stored is None and not self._load_failed:
                # First run: everything so far is history, not news.
                self._seen = set()
                self.mark_seen(m.key for m in view.decided)
                return []
            # After a failed read an empty store is not proof of a first run:
            # report what is unseen (the age limit below caps it).
            self._seen = set((stored or {}).get("seen", []))
        unseen = [m for m in view.decided if m.key not in self._seen]
        # Too old to be news (e.g. the event entity was disabled for weeks).
        oldest = dt_util.now() - RESULT_EVENT_MAX_AGE
        stale = [m.key for m in unseen if m.kickoff < oldest]
        if stale:
            self.mark_seen(stale)
        return [m for m in unseen if m.kickoff >= oldest]

    @callback
    def mark_seen(self, keys: Iterable[str]) -> None:
        """Remember reported results, in memory now and on disk soon."""
        self._seen = (self._seen or set()) | set(keys)
        self.hass.async_create_task(self._async_save())

    async def _async_save(self) -> None:
        async with self._lock:
            try:
                # Merge with what is stored, so an older coordinator of this
                # entry (reload during a poll) can't drop keys a newer one saved.
                stored = await self._store.async_load() or {}
                seen = set(stored.get("seen", [])) | (self._seen or set())
                await self._store.async_save({"seen": sorted(seen)})
            except (HomeAssistantError, OSError, ValueError) as err:
                _LOGGER.warning("Could not save seen results: %s", err)
