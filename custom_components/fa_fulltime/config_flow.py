"""Config flow: search the league, pick the division, then the team."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.util import dt as dt_util

from .api import FullTimeClient, FullTimeError
from .const import (
    CONF_API_URL,
    CONF_DIVISION_ID,
    CONF_DIVISION_NAME,
    CONF_LEAGUE_ID,
    CONF_LEAGUE_NAME,
    CONF_SCAN_INTERVAL,
    CONF_TEAM,
    DEFAULT_API_URL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    FULLTIME_TZ,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .parse import parse_matches, teams

CONF_LEAGUE_QUERY = "league_query"


def _select(options: list[tuple[str, str]]) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=[SelectOptionDict(value=v, label=label) for v, label in options],
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


class FullTimeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add one team."""

    VERSION = 1

    def __init__(self) -> None:
        """Start with nothing picked."""
        self._api_url = DEFAULT_API_URL
        self._leagues: list[dict[str, Any]] = []
        self._league: dict[str, Any] = {}
        self._division: dict[str, str] = {}
        self._teams: list[str] = []

    def _client(self) -> FullTimeClient:
        return FullTimeClient(async_get_clientsession(self.hass), self._api_url)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for (part of) the league name."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._api_url = user_input[CONF_API_URL].strip().rstrip("/")
            try:
                self._leagues = await self._client().search_leagues(
                    user_input[CONF_LEAGUE_QUERY].strip()
                )
            except FullTimeError:
                errors["base"] = "cannot_connect"
            else:
                if self._leagues:
                    return await self.async_step_league()
                errors[CONF_LEAGUE_QUERY] = "no_leagues"
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LEAGUE_QUERY): str,
                    vol.Required(CONF_API_URL, default=self._api_url): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.URL)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_league(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the league (skipped when the search found one)."""
        if user_input is None and len(self._leagues) == 1:
            user_input = {CONF_LEAGUE_ID: self._leagues[0]["id"]}
        if user_input is not None:
            self._league = next(
                lg for lg in self._leagues if lg["id"] == user_input[CONF_LEAGUE_ID]
            )
            if not self._league["divisions"]:
                return self.async_abort(reason="no_divisions")
            return await self.async_step_division()
        return self.async_show_form(
            step_id="league",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LEAGUE_ID): _select(
                        [(lg["id"], lg["name"]) for lg in self._leagues]
                    )
                }
            ),
        )

    async def async_step_division(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the division, then load its teams."""
        errors: dict[str, str] = {}
        divisions = self._league["divisions"]
        if user_input is not None:
            self._division = next(
                d for d in divisions if d["id"] == user_input[CONF_DIVISION_ID]
            )
            client = self._client()
            try:
                fixtures = await client.fixtures(self._division["id"])
                results = await client.results(self._division["id"])
            except FullTimeError:
                errors["base"] = "cannot_connect"
            else:
                tz = dt_util.get_time_zone(FULLTIME_TZ)
                self._teams = teams(parse_matches(fixtures, results, tz))
                if self._teams:
                    return await self.async_step_team()
                errors[CONF_DIVISION_ID] = "no_teams"
        return self.async_show_form(
            step_id="division",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DIVISION_ID): _select(
                        [(d["id"], d["name"]) for d in divisions]
                    )
                }
            ),
            description_placeholders={"league": self._league["name"]},
            errors=errors,
        )

    async def async_step_team(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the team."""
        if user_input is not None:
            team = user_input[CONF_TEAM]
            await self.async_set_unique_id(f"{self._division['id']}_{team}")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=team,
                data={
                    CONF_API_URL: self._api_url,
                    CONF_LEAGUE_ID: self._league["id"],
                    CONF_LEAGUE_NAME: self._league["name"],
                    CONF_DIVISION_ID: self._division["id"],
                    CONF_DIVISION_NAME: self._division["name"],
                    CONF_TEAM: team,
                },
            )
        return self.async_show_form(
            step_id="team",
            data_schema=vol.Schema(
                {vol.Required(CONF_TEAM): _select([(t, t) for t in self._teams])}
            ),
            description_placeholders={"division": self._division["name"]},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> FullTimeOptionsFlow:
        """Options: poll interval and API URL."""
        return FullTimeOptionsFlow()


class FullTimeOptionsFlow(OptionsFlow):
    """Change how often and where the team is fetched."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options."""
        if user_input is not None:
            user_input[CONF_API_URL] = user_input[CONF_API_URL].strip().rstrip("/")
            return self.async_create_entry(data=user_input)
        entry = self.config_entry
        api_url = entry.options.get(CONF_API_URL) or entry.data.get(
            CONF_API_URL, DEFAULT_API_URL
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=entry.options.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                    ): vol.All(
                        NumberSelector(
                            NumberSelectorConfig(
                                min=MIN_SCAN_INTERVAL,
                                max=MAX_SCAN_INTERVAL,
                                step=1,
                                unit_of_measurement="min",
                                mode=NumberSelectorMode.BOX,
                            )
                        ),
                        vol.Coerce(int),
                    ),
                    vol.Required(CONF_API_URL, default=api_url): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.URL)
                    ),
                }
            ),
        )
