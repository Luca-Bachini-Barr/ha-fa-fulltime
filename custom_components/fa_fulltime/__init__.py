"""FA Full-Time: grassroots football fixtures, results and table for one team.

Data comes from FA Full-Time through the unofficial FullTime API
(github.com/jwhughes-work/FullTimeAPI), public or self-hosted.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .api import FullTimeClient
from .const import CONF_API_URL, DEFAULT_API_URL, DOMAIN, PLATFORMS
from .coordinator import STORAGE_VERSION, FullTimeCoordinator

type FullTimeConfigEntry = ConfigEntry[FullTimeCoordinator]


def api_url(entry: ConfigEntry) -> str:
    """The API URL: options win over the URL given at setup."""
    return (
        entry.options.get(CONF_API_URL)
        or entry.data.get(CONF_API_URL)
        or DEFAULT_API_URL
    )


async def async_setup_entry(hass: HomeAssistant, entry: FullTimeConfigEntry) -> bool:
    """Fetch the division once, then set up the entities."""
    client = FullTimeClient(async_get_clientsession(hass), api_url(entry))
    coordinator = FullTimeCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FullTimeConfigEntry) -> bool:
    """Unload the entities."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete the stored list of seen results."""
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}").async_remove()


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
