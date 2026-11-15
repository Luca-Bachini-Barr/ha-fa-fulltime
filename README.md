# FA Full-Time for Home Assistant

Follow a grassroots football team from [FA Full-Time](https://fulltime.thefa.com/) — the FA's fixtures, results and tables system used by most youth and adult leagues in England — in Home Assistant: next match, last result, league position, form, a fixtures calendar and an event when a new result comes in.

FA Full-Time has no API, and it sits behind Cloudflare bot checks that block ordinary HTTP clients. This integration therefore reads it through the unofficial **[FullTime API](https://github.com/jwhughes-work/FullTimeAPI)**, which scrapes Full-Time with a real headless browser and returns JSON. By default it uses the public instance at `https://faapi.jwhsolutions.co.uk`; you can run your own copy and point the integration at it.

> Not affiliated with or endorsed by The Football Association. All data belongs to its owners.

## Install

HACS → ⋮ → **Custom repositories** → add `https://github.com/Luca-Bachini-Barr/ha-fa-fulltime` as an *Integration*, install **FA Full-Time**, restart Home Assistant.

Or copy `custom_components/fa_fulltime` into your config's `custom_components` folder and restart.

## Set up

**Settings → Devices & services → Add integration → FA Full-Time**

1. Type part of the league's name (e.g. `Milton Keynes`).
2. Pick the league (skipped if only one matches) and the division.
3. Pick the team from the teams playing in that division.

Add the integration again for each extra team. Loading a division can take up to a minute: the API renders Full-Time pages in a browser when they are not cached.

**Options:** how often to check (default every 120 minutes, 30–1440) and the API URL.

**New season:** Full-Time gives every division a new ID each season. When the team no longer appears in the old division the entities go unavailable and the log says so: delete the entry and add the team again.

## Entities

One device per team, named after the team.

| Entity | State | Attributes |
|---|---|---|
| `sensor.<team>_next_match` | Kick-off (timestamp) | `opponent`, `home_away`, `venue`, `competition`, `home_team`, `away_team`, `upcoming` (next 5 matches) |
| `sensor.<team>_last_result` | `win` / `draw` / `loss` | `score` (home first, e.g. `4–1`), `half_time`, `goals_for`, `goals_against`, `opponent`, `home_away`, `kickoff`, `venue` |
| `sensor.<team>_league_position` | Position | `points`, `played`, `won`, `drawn`, `lost`, `goals_for`, `goals_against`, `goal_difference`, `teams`, `table` (whole table) |
| `sensor.<team>_points` | Points | |
| `sensor.<team>_form` | Last 5 results, oldest first, e.g. `WDDWW` | `results` (those matches) |
| `sensor.<team>_division_results` | Date of the latest day with results in the division | `today` (every division match today, played or not), `latest_date`, `latest` (every match on that day). Each match has `home_team`, `away_team`, `status`, `score`, `home_score`, `away_score`, `half_time`, `venue` |
| `calendar.<team>_matches` | On during a match | Every match this season; played ones show the score, postponed/abandoned ones are labelled |
| `event.<team>_new_result` | Event types `win`, `draw`, `loss` | The match, as on `last_result` |

`upcoming`, `table`, `results`, `today` and `latest` are not stored in the recorder.

A match stays the **next match** until 90 minutes after kick-off. A match without a kick-off time on Full-Time is an all-day calendar event, stays the next match all day, and its sensor shows midnight UK time; every match dict has `date` and `time_known` so cards can tell.

### The league table

The table is **worked out from the results**, not read from Full-Time: many youth leagues don't publish a table, and the API does not always return one. It uses 3 points for a win and 1 for a draw, then goal difference, goals scored and name. A walkover or awarded match counts as a win and a loss with no goals. Points deductions and league-specific rules are not known to the integration, so the table can differ from an official one.

### New result event

`event.<team>_new_result` fires once for each new result of the team (including walkovers). Results already in Full-Time when the team is added do not fire, and neither do results more than 14 days old when they first appear. A result counts as seen only after the event has fired, and seen results are stored, so a result that comes in while Home Assistant is down fires after it starts.

```yaml
triggers:
  - trigger: state
    entity_id: event.wingrave_juniors_u15_wingrave_wasps_new_result
actions:
  - action: notify.mobile_app_phone
    data:
      title: "Full time"
      message: >
        {{ state_attr(trigger.entity_id, 'home_team') }}
        {{ state_attr(trigger.entity_id, 'score') }}
        {{ state_attr(trigger.entity_id, 'away_team') }}
```

## Limits

- Full-Time's JSON has no fixture IDs; matches are identified by date and teams.
- No referees, addresses, line-ups or scorers — those live on Full-Time pages the API does not read.
- The public API is a free service run by its author; keep the poll interval sensible, or self-host it.

## Development

```sh
uv venv && uv pip install pytest-homeassistant-custom-component
.venv/bin/pytest --cov=custom_components.fa_fulltime
```

`tests/fixtures.json` and `tests/results.json` are real API responses for one division (2026-11-15).

## Licence

MIT
