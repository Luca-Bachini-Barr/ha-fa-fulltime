"""Constants for FA Full-Time."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "fa_fulltime"
PLATFORMS = [Platform.CALENDAR, Platform.EVENT, Platform.SENSOR]

CONF_API_URL = "api_url"
CONF_LEAGUE_ID = "league_id"
CONF_LEAGUE_NAME = "league_name"
CONF_DIVISION_ID = "division_id"
CONF_DIVISION_NAME = "division_name"
CONF_TEAM = "team"
CONF_SCAN_INTERVAL = "scan_interval"

# Unofficial JSON API over FA Full-Time (github.com/jwhughes-work/FullTimeAPI).
# Full-Time itself sits behind Cloudflare bot checks that block plain HTTP
# clients, so this integration talks to that API (public or self-hosted).
DEFAULT_API_URL = "https://faapi.jwhsolutions.co.uk"
DEFAULT_SCAN_INTERVAL = 120  # minutes
MIN_SCAN_INTERVAL = 30
MAX_SCAN_INTERVAL = 1440

# The API scrapes Full-Time with a headless browser on a cache miss.
REQUEST_TIMEOUT = 120

# Full-Time lists kick-off times in UK time without a zone.
FULLTIME_TZ = "Europe/London"
MATCH_DURATION = timedelta(minutes=90)
# Results older than this when first seen don't fire the new-result event.
RESULT_EVENT_MAX_AGE = timedelta(days=14)
FORM_LENGTH = 5
UPCOMING_COUNT = 5

POINTS_WIN = 3
POINTS_DRAW = 1
