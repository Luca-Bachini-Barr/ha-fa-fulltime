"""Sensors: next match, last result, league position, points and form."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FullTimeConfigEntry
from .const import UPCOMING_COUNT
from .coordinator import FullTimeCoordinator
from .entity import FullTimeEntity
from .parse import OUTCOME_DRAW, OUTCOME_LOSS, OUTCOME_WIN, TeamView


def _next_attrs(view: TeamView) -> dict[str, Any]:
    match = view.next_match
    attrs: dict[str, Any] = match.as_dict(view.team) if match else {}
    attrs["upcoming"] = [m.as_dict(view.team) for m in view.upcoming[:UPCOMING_COUNT]]
    return attrs


def _last_attrs(view: TeamView) -> dict[str, Any]:
    match = view.last_result
    return match.as_dict(view.team) if match else {}


def _position_attrs(view: TeamView) -> dict[str, Any]:
    attrs: dict[str, Any] = view.row.as_dict() if view.row else {}
    attrs.pop("position", None)
    attrs["teams"] = len(view.table)
    attrs["table"] = [row.as_dict() for row in view.table]
    return attrs


def _form_attrs(view: TeamView) -> dict[str, Any]:
    # Same matches as the form letters, oldest first.
    count = len(view.form())
    recent = view.decided[-count:] if count else []
    return {"results": [m.as_dict(view.team) for m in recent]}


@dataclass(frozen=True, kw_only=True)
class FullTimeSensorDescription(SensorEntityDescription):
    """How a sensor reads the team view."""

    value: Callable[[TeamView], Any]
    attrs: Callable[[TeamView], dict[str, Any]] = lambda view: {}


SENSORS: tuple[FullTimeSensorDescription, ...] = (
    FullTimeSensorDescription(
        key="next_match",
        device_class=SensorDeviceClass.TIMESTAMP,
        value=lambda v: v.next_match.kickoff if v.next_match else None,
        attrs=_next_attrs,
    ),
    FullTimeSensorDescription(
        key="last_result",
        device_class=SensorDeviceClass.ENUM,
        options=[OUTCOME_WIN, OUTCOME_DRAW, OUTCOME_LOSS],
        value=lambda v: v.last_result.outcome(v.team) if v.last_result else None,
        attrs=_last_attrs,
    ),
    FullTimeSensorDescription(
        key="league_position",
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda v: v.row.position if v.row and v.row.played else None,
        attrs=_position_attrs,
    ),
    FullTimeSensorDescription(
        key="points",
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda v: v.row.points if v.row else None,
    ),
    FullTimeSensorDescription(
        key="form",
        value=lambda v: v.form() or None,
        attrs=_form_attrs,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FullTimeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the team's sensors."""
    async_add_entities(
        FullTimeSensor(entry.runtime_data, description) for description in SENSORS
    )


class FullTimeSensor(FullTimeEntity, SensorEntity):
    """A value from the team view."""

    entity_description: FullTimeSensorDescription
    # Lists of matches and the table: shown live, kept out of the database.
    _unrecorded_attributes = frozenset({"upcoming", "table", "results"})

    def __init__(
        self, coordinator: FullTimeCoordinator, description: FullTimeSensorDescription
    ) -> None:
        """Set up the sensor for one description."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> str | int | datetime | None:
        """The value from the latest poll."""
        return self.entity_description.value(self.coordinator.data.view)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Details from the latest poll."""
        return self.entity_description.attrs(self.coordinator.data.view)
