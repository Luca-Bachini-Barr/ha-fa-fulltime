"""Parsing fixtures and results, the table and the team view."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.fa_fulltime.parse import (
    STATUS_ABANDONED,
    STATUS_AWAY_AWARDED,
    STATUS_CANCELLED,
    STATUS_HOME_AWARDED,
    STATUS_PLAYED,
    STATUS_POSTPONED,
    STATUS_SCHEDULED,
    STATUS_UNKNOWN,
    Match,
    league_table,
    parse_kickoff,
    parse_matches,
    parse_score,
    team_view,
    teams,
)

from .conftest import FIXTURES, RESULTS, TEAM

UK = ZoneInfo("Europe/London")
NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UK)
GRACE = timedelta(minutes=90)


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        ("1 - 3 (HT 0-2)", (STATUS_PLAYED, 1, 3, "0–2")),
        ("4 - 1", (STATUS_PLAYED, 4, 1, None)),
        ("10 - 0 (HT 5 - 0)", (STATUS_PLAYED, 10, 0, "5–0")),
        ("Postponed P - P", (STATUS_POSTPONED, None, None, None)),
        ("Home Walkover H - W", (STATUS_HOME_AWARDED, None, None, None)),
        ("Away Walkover A - W", (STATUS_AWAY_AWARDED, None, None, None)),
        ("Home Win Awarded", (STATUS_HOME_AWARDED, None, None, None)),
        ("Walkover", (STATUS_UNKNOWN, None, None, None)),
        ("Abandoned A - A", (STATUS_ABANDONED, None, None, None)),
        ("Match Cancelled", (STATUS_CANCELLED, None, None, None)),
        ("Void", (STATUS_CANCELLED, None, None, None)),
        ("TBC", (STATUS_UNKNOWN, None, None, None)),
        ("", (STATUS_UNKNOWN, None, None, None)),
    ],
)
def test_parse_score(score, expected) -> None:
    """Score strings as Full-Time writes them."""
    got = parse_score({"score": score})
    assert (
        got["status"],
        got.get("home_score"),
        got.get("away_score"),
        got.get("half_time"),
    ) == expected


def test_parse_score_from_halves() -> None:
    """An empty score with numeric home/away scores still counts."""
    got = parse_score({"score": None, "homeScore": "2", "awayScore": "3"})
    assert (got["status"], got["home_score"], got["away_score"]) == (
        STATUS_PLAYED,
        2,
        3,
    )


def test_parse_kickoff() -> None:
    """UK date and time, with or without the time or century."""
    assert parse_kickoff("05/12/26 09:00", UK) == (
        datetime(2026, 12, 5, 9, 0, tzinfo=UK),
        True,
    )
    assert parse_kickoff("05/07/2026 18:30", UK)[0].utcoffset() == timedelta(hours=1)
    assert parse_kickoff("05/12/26", UK) == (datetime(2026, 12, 5, tzinfo=UK), False)
    assert parse_kickoff("next week", UK) is None
    assert parse_kickoff(None, UK) is None


def test_parse_matches_skips_bad_rows_and_unescapes() -> None:
    """Rows without a date or teams are dropped; HTML entities decoded."""
    matches = parse_matches(
        [
            {"fixtureDateTime": "x", "homeTeam": "A", "awayTeam": "B"},
            {"fixtureDateTime": "05/12/26 09:00", "homeTeam": "", "awayTeam": "B"},
            {
                "fixtureDateTime": "05/12/26 09:00",
                "homeTeam": "Bow &amp; Arrow",
                "awayTeam": "B",
                "location": " ",
            },
        ],
        [{"fixtureDateTime": "x", "homeTeam": "A", "awayTeam": "B", "score": "1 - 0"}],
        UK,
    )
    assert [(m.home, m.venue) for m in matches] == [("Bow & Arrow", None)]


def test_result_replaces_fixture_and_keeps_venue() -> None:
    """A postponed game listed in both lists appears once, with its venue."""
    matches = parse_matches(FIXTURES, RESULTS, UK)
    postponed = [m for m in matches if m.status == STATUS_POSTPONED]
    assert len(postponed) == 1
    assert postponed[0].home == "MK United U15 Lions"
    assert postponed[0].venue == "HODGE LEA"
    keys = [m.key for m in matches]
    assert len(keys) == len(set(keys))


def test_teams() -> None:
    """Nine teams in the division."""
    names = teams(parse_matches(FIXTURES, RESULTS, UK))
    assert len(names) == 9
    assert TEAM in names


def test_league_table() -> None:
    """Matches the table worked out by hand on 2026-11-15."""
    table = league_table(parse_matches(FIXTURES, RESULTS, UK))
    got = [
        (r.team, r.played, r.won, r.drawn, r.lost, r.goal_difference, r.points)
        for r in table
    ]
    assert got[:4] == [
        ("Shenley FC U15 Tigers", 8, 4, 3, 1, 7, 15),
        ("MK United U15 Lions", 6, 4, 1, 1, 8, 13),
        ("Hanslope Hornets U15", 7, 3, 3, 1, 3, 12),
        (TEAM, 6, 3, 2, 1, 7, 11),
    ]
    assert got[-1][0] == "Padbury Village U15 Cougars"
    assert [r.position for r in table] == list(range(1, 10))


def test_table_tie_breaks_and_away_walkover() -> None:
    """Points, then goal difference, then goals, then name."""
    k = datetime(2026, 9, 1, 9, 0, tzinfo=UK)
    matches = [
        Match(k, "A", "B", STATUS_PLAYED, home_score=2, away_score=0),
        Match(k, "C", "D", STATUS_PLAYED, home_score=3, away_score=1),
        Match(k, "E", "F", STATUS_AWAY_AWARDED),
        Match(k, "G", "H", STATUS_POSTPONED),
    ]
    table = league_table(matches)
    assert [r.team for r in table[:3]] == ["C", "A", "F"]
    f = next(r for r in table if r.team == "F")
    assert (f.played, f.won, f.points, f.goals_for) == (1, 1, 3, 0)
    g = next(r for r in table if r.team == "G")
    assert g.played == 0


def test_team_view() -> None:
    """Next match, last result and form for the Wasps."""
    view = team_view(parse_matches(FIXTURES, RESULTS, UK), TEAM, NOW, GRACE)
    nxt = view.next_match
    assert nxt.kickoff == datetime(2026, 12, 5, 9, 0, tzinfo=UK)
    assert nxt.opponent(TEAM) == "Real Bedford Wixams U15 Reds"
    assert nxt.as_dict(TEAM)["home_away"] == "away"
    assert nxt.as_dict(TEAM)["venue"] == "WANDERERS PARK"
    last = view.last_result
    assert last.as_dict(TEAM) | {} == {
        "kickoff": "2026-11-14T09:00:00+00:00",
        "date": "2026-11-14",
        "time_known": True,
        "home_team": TEAM,
        "away_team": "Padbury Village U15 Cougars",
        "status": STATUS_PLAYED,
        "competition": "Division 5 U15",
        "score": "4–1",
        "home_score": 4,
        "away_score": 1,
        "opponent": "Padbury Village U15 Cougars",
        "home_away": "home",
        "outcome": "win",
        "goals_for": 4,
        "goals_against": 1,
    }
    # 12 Sep walkover loss, then W D D W W
    assert view.form() == "WDDWW"
    assert view.form(10) == "LWDDWW"
    assert view.row.position == 4
    assert len(view.upcoming) == 10


def test_walkover_from_away_side() -> None:
    """The walkover against the Wasps is a loss with no goals."""
    view = team_view(parse_matches(FIXTURES, RESULTS, UK), TEAM, NOW, GRACE)
    walkover = view.decided[0]
    assert walkover.status == STATUS_HOME_AWARDED
    assert walkover.outcome(TEAM) == "loss"
    assert walkover.goals(TEAM) is None
    assert walkover.score() == "Walkover"
    assert "goals_for" not in walkover.as_dict(TEAM)


def test_match_stays_upcoming_during_the_game() -> None:
    """Until 90 minutes after kick-off the game is still the next match."""
    k = datetime(2026, 12, 5, 9, 0, tzinfo=UK)
    matches = [Match(k, TEAM, "B"), Match(k + timedelta(days=7), "C", TEAM)]
    assert (
        team_view(matches, TEAM, k + timedelta(minutes=80), GRACE).next_match
        is matches[0]
    )
    assert (
        team_view(matches, TEAM, k + timedelta(minutes=95), GRACE).next_match
        is matches[1]
    )
    assert team_view(matches, TEAM, k + timedelta(days=30), GRACE).next_match is None


def test_undecided_match_has_no_outcome() -> None:
    """Scheduled and postponed games have no outcome or score."""
    k = datetime(2026, 12, 5, 9, 0, tzinfo=UK)
    for status in (STATUS_SCHEDULED, STATUS_POSTPONED):
        match = Match(k, TEAM, "B", status)
        assert match.outcome(TEAM) is None
        assert match.score() is None
        assert match.goals(TEAM) is None
    played = Match(k, "B", TEAM, STATUS_PLAYED, home_score=1, away_score=1)
    assert played.outcome(TEAM) == "draw"
    assert played.goals(TEAM) == (1, 1)
    lost = Match(k, "B", TEAM, STATUS_PLAYED, home_score=2, away_score=1)
    assert lost.outcome(TEAM) == "loss"


def test_unreadable_result_keeps_fixture() -> None:
    """A result line with an unknown status doesn't hide the fixture."""
    fixture = {
        "fixtureDateTime": "05/12/26 09:00",
        "homeTeam": TEAM,
        "awayTeam": "B",
        "location": "PARK",
    }
    result = {
        "fixtureDateTime": "05/12/26 09:00",
        "homeTeam": TEAM,
        "awayTeam": "B",
        "score": "TBC",
    }
    [match] = parse_matches([fixture], [result], UK)
    assert match.status == STATUS_SCHEDULED
    assert match.venue == "PARK"
    # Without a fixture the unknown line is still listed.
    [match] = parse_matches([], [result], UK)
    assert match.status == STATUS_UNKNOWN


def test_date_only_fixture_stays_upcoming_all_day() -> None:
    """No kick-off time: next match until the day is over."""
    k = datetime(2026, 12, 5, 0, 0, tzinfo=UK)
    matches = [Match(k, TEAM, "B", time_known=False)]
    evening = datetime(2026, 12, 5, 21, 0, tzinfo=UK)
    assert team_view(matches, TEAM, evening, GRACE).next_match is matches[0]
    assert team_view(matches, TEAM, k + timedelta(days=1), GRACE).next_match is None
    data = matches[0].as_dict(TEAM)
    assert (data["date"], data["time_known"]) == ("2026-12-05", False)


def test_division_matchdays() -> None:
    """The whole division's matches by day, and the latest day with results."""
    view = team_view(parse_matches(FIXTURES, RESULTS, UK), TEAM, NOW, GRACE)
    assert view.today == date(2026, 11, 15)
    assert view.matches_on(view.today) == []
    assert view.latest_matchday == date(2026, 11, 14)
    day = view.matches_on(date(2026, 11, 14))
    assert [(m.home, m.status) for m in day] == [
        ("Deanshanger Colts U15 Stallions", STATUS_PLAYED),
        ("MK United U15 Lions", STATUS_POSTPONED),
        ("Shenley FC U15 Tigers", STATUS_PLAYED),
        (TEAM, STATUS_PLAYED),
    ]
    assert day[0].as_dict()["home_score"] == 1
    assert "home_score" not in day[1].as_dict()
    # On match day, today's list has every game, played or not yet.
    saturday = datetime(2026, 12, 5, 10, 0, tzinfo=UK)
    view = team_view(parse_matches(FIXTURES, RESULTS, UK), TEAM, saturday, GRACE)
    assert len(view.matches_on(view.today)) == 4
    assert view.latest_matchday == date(2026, 11, 14)


def test_latest_matchday_ignores_future_and_undecided() -> None:
    """Postponed-only days and results dated after today don't count."""
    k = datetime(2026, 11, 7, 9, 0, tzinfo=UK)
    matches = [
        Match(k, "A", TEAM, STATUS_PLAYED, home_score=1, away_score=0),
        Match(k + timedelta(days=7), "B", TEAM, STATUS_POSTPONED),
        Match(
            k + timedelta(days=30), "C", TEAM, STATUS_PLAYED, home_score=0, away_score=0
        ),
    ]
    view = team_view(matches, TEAM, NOW, GRACE)
    assert view.latest_matchday == date(2026, 11, 7)
    assert team_view([], TEAM, NOW, GRACE).latest_matchday is None
