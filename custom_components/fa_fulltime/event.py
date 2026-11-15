"""Event entity: fires when a new result for the team comes in."""

from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FullTimeConfigEntry
from .coordinator import FullTimeCoordinator
from .entity import FullTimeEntity
from .parse import OUTCOME_DRAW, OUTCOME_LOSS, OUTCOME_WIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FullTimeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the result event entity."""
    async_add_entities([FullTimeResultEvent(entry.runtime_data)])


class FullTimeResultEvent(FullTimeEntity, EventEntity):
    """win / draw / loss, with the match as event data."""

    _attr_event_types = [OUTCOME_WIN, OUTCOME_DRAW, OUTCOME_LOSS]

    def __init__(self, coordinator: FullTimeCoordinator) -> None:
        """Set up the event entity."""
        super().__init__(coordinator, "new_result")

    async def async_added_to_hass(self) -> None:
        """Report results found by the first poll, which ran before this existed."""
        await super().async_added_to_hass()
        self._fire_new()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._fire_new()
        super()._handle_coordinator_update()

    @callback
    def _fire_new(self) -> None:
        data = self.coordinator.data
        team = data.view.team
        for match in data.new_results:
            outcome = match.outcome(team)
            if outcome is not None:
                self._trigger_event(outcome, match.as_dict(team))
                # One state write per result, so each one reaches automations.
                self.async_write_ha_state()
        # Each result fires once, even if the entity is re-added.
        data.new_results = []
