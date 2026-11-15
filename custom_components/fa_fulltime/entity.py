"""Base entity: one device per team."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DIVISION_NAME, CONF_LEAGUE_NAME, DOMAIN
from .coordinator import FullTimeCoordinator


class FullTimeEntity(CoordinatorEntity[FullTimeCoordinator]):
    """An entity of the team's device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: FullTimeCoordinator, key: str) -> None:
        """Name the entity after its key and attach it to the team device."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        league = entry.data.get(CONF_LEAGUE_NAME)
        division = entry.data.get(CONF_DIVISION_NAME)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=coordinator.team,
            manufacturer="FA Full-Time",
            model=" – ".join(p for p in (league, division) if p) or None,
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://fulltime.thefa.com/",
        )
