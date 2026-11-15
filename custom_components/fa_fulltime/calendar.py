"""Calendar of the team's fixtures and results."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import FullTimeConfigEntry
from .const import MATCH_DURATION
from .coordinator import FullTimeCoordinator
from .entity import FullTimeEntity
from .parse import (
    STATUS_ABANDONED,
    STATUS_CANCELLED,
    STATUS_PLAYED,
    STATUS_POSTPONED,
    STATUS_SCHEDULED,
    Match,
)

_STATUS_LABEL = {
    STATUS_POSTPONED: "Postponed",
    STATUS_ABANDONED: "Abandoned",
    STATUS_CANCELLED: "Cancelled",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FullTimeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the team's calendar."""
    async_add_entities([FullTimeCalendar(entry.runtime_data)])


def match_event(match: Match, team: str) -> CalendarEvent:
    """A calendar event for a match: 'Home v Away', or the score once known."""
    score = match.score()
    if score == "Walkover":
        summary = f"{match.home} v {match.away} (walkover)"
    elif score is not None:
        summary = f"{match.home} {score} {match.away}"
    else:
        summary = f"{match.home} v {match.away}"
    if label := _STATUS_LABEL.get(match.status):
        summary = f"{label}: {summary}"

    lines = ["Home" if match.is_home(team) else "Away"]
    if match.competition:
        lines.append(match.competition)
    if match.half_time:
        lines.append(f"Half time {match.half_time}")
    if match.score_text and match.status not in (STATUS_PLAYED, STATUS_SCHEDULED):
        lines.append(match.score_text)

    start: datetime | date
    end: datetime | date
    if match.time_known:
        start = match.kickoff
        end = match.kickoff + MATCH_DURATION
    else:
        start = match.kickoff.date()
        end = match.kickoff.date() + timedelta(days=1)
    return CalendarEvent(
        start=start,
        end=end,
        summary=summary,
        location=match.venue,
        description="\n".join(lines),
        uid=match.key,
    )


def _event_end(event: CalendarEvent) -> datetime:
    return dt_util.as_local(event.end_datetime_local)


class FullTimeCalendar(FullTimeEntity, CalendarEntity):
    """Every match of the team this season."""

    def __init__(self, coordinator: FullTimeCoordinator) -> None:
        """Set up the calendar."""
        super().__init__(coordinator, "matches")

    def _events(self) -> list[CalendarEvent]:
        view = self.coordinator.data.view
        return [match_event(m, view.team) for m in view.matches]

    @property
    def event(self) -> CalendarEvent | None:
        """The match on now, or the next one."""
        now = dt_util.now()
        upcoming = [e for e in self._events() if _event_end(e) > now]
        return min(upcoming, key=lambda e: e.start_datetime_local, default=None)

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Matches overlapping the range."""
        return [
            e
            for e in self._events()
            if e.start_datetime_local < end_date and _event_end(e) > start_date
        ]
