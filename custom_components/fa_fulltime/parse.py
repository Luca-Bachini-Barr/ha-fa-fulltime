"""Turn FullTime API fixtures and results into matches, a team view and a table.

Pure functions, no Home Assistant objects, so they are easy to test.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any

from .const import FORM_LENGTH, POINTS_DRAW, POINTS_WIN

STATUS_SCHEDULED = "scheduled"
STATUS_PLAYED = "played"
STATUS_HOME_AWARDED = "home_awarded"  # home walkover / match awarded to home
STATUS_AWAY_AWARDED = "away_awarded"
STATUS_POSTPONED = "postponed"
STATUS_ABANDONED = "abandoned"
STATUS_CANCELLED = "cancelled"
STATUS_UNKNOWN = "unknown"

# Statuses that count in the table and in a team's form.
DECIDED = (STATUS_PLAYED, STATUS_HOME_AWARDED, STATUS_AWAY_AWARDED)

OUTCOME_WIN = "win"
OUTCOME_DRAW = "draw"
OUTCOME_LOSS = "loss"
OUTCOME_LETTER = {OUTCOME_WIN: "W", OUTCOME_DRAW: "D", OUTCOME_LOSS: "L"}

_SCORE = re.compile(r"^\s*(\d+)\s*-\s*(\d+)(?:\s*\(\s*HT\s*(\d+)\s*-\s*(\d+)\s*\))?")
_DATE_FORMATS = ("%d/%m/%y %H:%M", "%d/%m/%Y %H:%M")
_DAY_FORMATS = ("%d/%m/%y", "%d/%m/%Y")


@dataclass(frozen=True)
class Match:
    """One fixture or result."""

    kickoff: datetime
    home: str
    away: str
    status: str = STATUS_SCHEDULED
    time_known: bool = True
    venue: str | None = None
    competition: str | None = None
    home_score: int | None = None
    away_score: int | None = None
    half_time: str | None = None
    score_text: str | None = None

    @property
    def key(self) -> str:
        """Stable ID: Full-Time's JSON has no fixture IDs."""
        return f"{self.kickoff.date().isoformat()}|{self.home}|{self.away}"

    def involves(self, team: str) -> bool:
        """True if `team` plays in this match."""
        return team in (self.home, self.away)

    def is_home(self, team: str) -> bool:
        """True if `team` is the home side."""
        return self.home == team

    def opponent(self, team: str) -> str:
        """The other side."""
        return self.away if self.home == team else self.home

    def goals(self, team: str) -> tuple[int, int] | None:
        """(for, against) for `team`, or None when no score was recorded."""
        if self.home_score is None or self.away_score is None:
            return None
        if self.home == team:
            return self.home_score, self.away_score
        return self.away_score, self.home_score

    def outcome(self, team: str) -> str | None:
        """win / draw / loss for `team`, None if the match was not decided."""
        if self.status == STATUS_HOME_AWARDED:
            return OUTCOME_WIN if self.home == team else OUTCOME_LOSS
        if self.status == STATUS_AWAY_AWARDED:
            return OUTCOME_LOSS if self.home == team else OUTCOME_WIN
        if self.status != STATUS_PLAYED:
            return None
        gf, ga = self.goals(team)  # type: ignore[misc]
        if gf > ga:
            return OUTCOME_WIN
        if gf == ga:
            return OUTCOME_DRAW
        return OUTCOME_LOSS

    def score(self) -> str | None:
        """'4–1' (home first), the status for undecided games, None if unplayed."""
        if self.status == STATUS_PLAYED:
            return f"{self.home_score}–{self.away_score}"
        if self.status in (STATUS_HOME_AWARDED, STATUS_AWAY_AWARDED):
            return "Walkover"
        return None

    def as_dict(self, team: str | None = None) -> dict[str, Any]:
        """Attributes for an entity, from `team`'s point of view if given."""
        data: dict[str, Any] = {
            "kickoff": self.kickoff.isoformat(),
            # Full-Time can list a date without a kick-off time; kickoff is
            # then midnight UK time and time_known is false.
            "date": self.kickoff.date().isoformat(),
            "time_known": self.time_known,
            "home_team": self.home,
            "away_team": self.away,
            "status": self.status,
        }
        if self.venue:
            data["venue"] = self.venue
        if self.competition:
            data["competition"] = self.competition
        if (score := self.score()) is not None:
            data["score"] = score
        if self.home_score is not None and self.away_score is not None:
            data["home_score"], data["away_score"] = self.home_score, self.away_score
        if self.half_time:
            data["half_time"] = self.half_time
        if team is not None and self.involves(team):
            data["opponent"] = self.opponent(team)
            data["home_away"] = "home" if self.is_home(team) else "away"
            if (outcome := self.outcome(team)) is not None:
                data["outcome"] = outcome
            if (goals := self.goals(team)) is not None:
                data["goals_for"], data["goals_against"] = goals
        return data


def _text(item: dict[str, Any], key: str) -> str | None:
    value = item.get(key)
    if value is None:
        return None
    value = html.unescape(str(value)).strip()
    return value or None


def parse_kickoff(value: str | None, tz: tzinfo) -> tuple[datetime, bool] | None:
    """'14/11/26 09:00' (UK time) -> (aware datetime, time known)."""
    if not value:
        return None
    value = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=tz), True
        except ValueError:
            pass
    for fmt in _DAY_FORMATS:
        try:
            day: date = datetime.strptime(value, fmt).date()
        except ValueError:
            continue
        return datetime.combine(day, time(0, 0), tz), False
    return None


def parse_score(item: dict[str, Any]) -> dict[str, Any]:
    """Status, scores and half-time from a result's score fields."""
    text = _text(item, "score") or ""
    found = _SCORE.match(text)
    if found is None:
        # The API sometimes leaves `score` empty but fills both halves.
        home, away = _text(item, "homeScore"), _text(item, "awayScore")
        if home and away and home.isdigit() and away.isdigit():
            found = _SCORE.match(f"{home} - {away}")
    if found is not None:
        half = f"{found[3]}–{found[4]}" if found[3] is not None else None
        return {
            "status": STATUS_PLAYED,
            "home_score": int(found[1]),
            "away_score": int(found[2]),
            "half_time": half,
            "score_text": text or None,
        }
    lower = text.lower()
    if "walkover" in lower or "awarded" in lower:
        if lower.startswith("home"):
            status = STATUS_HOME_AWARDED
        elif lower.startswith("away"):
            status = STATUS_AWAY_AWARDED
        else:
            status = STATUS_UNKNOWN
    elif "postpone" in lower:
        status = STATUS_POSTPONED
    elif "abandon" in lower:
        status = STATUS_ABANDONED
    elif "cancel" in lower or "void" in lower:
        status = STATUS_CANCELLED
    else:
        status = STATUS_UNKNOWN
    return {"status": status, "score_text": text or None}


def _match(item: dict[str, Any], tz: tzinfo, **extra: Any) -> Match | None:
    when = parse_kickoff(_text(item, "fixtureDateTime"), tz)
    home, away = _text(item, "homeTeam"), _text(item, "awayTeam")
    if when is None or not home or not away:
        return None
    return Match(
        kickoff=when[0],
        time_known=when[1],
        home=home,
        away=away,
        venue=_text(item, "location"),
        competition=_text(item, "competition") or _text(item, "division"),
        **extra,
    )


def parse_matches(
    fixtures: list[dict[str, Any]], results: list[dict[str, Any]], tz: tzinfo
) -> list[Match]:
    """All matches of a division, sorted by kick-off.

    A result replaces the fixture with the same date and teams. A postponed
    game can stay in the fixture list with its old date; it then appears once,
    as postponed.
    """
    matches: dict[str, Match] = {}
    for item in fixtures:
        if (match := _match(item, tz)) is not None:
            matches[match.key] = match
    for item in results:
        if (match := _match(item, tz, **parse_score(item))) is None:
            continue
        old = matches.get(match.key)
        if match.status == STATUS_UNKNOWN and old is not None:
            # An unreadable result line says nothing new: keep the fixture.
            continue
        if old is not None and match.venue is None and old.venue:
            match = Match(**{**match.__dict__, "venue": old.venue})
        matches[match.key] = match
    return sorted(matches.values(), key=lambda m: (m.kickoff, m.home))


def teams(matches: list[Match]) -> list[str]:
    """Every team name in the division, sorted."""
    return sorted({m.home for m in matches} | {m.away for m in matches})


@dataclass
class TableRow:
    """A team's line in the league table."""

    team: str
    played: int = 0
    won: int = 0
    drawn: int = 0
    lost: int = 0
    goals_for: int = 0
    goals_against: int = 0
    points: int = 0
    position: int = 0

    @property
    def goal_difference(self) -> int:
        """Goals for minus goals against."""
        return self.goals_for - self.goals_against

    def as_dict(self) -> dict[str, Any]:
        """Row as attributes."""
        return {
            "position": self.position,
            "team": self.team,
            "played": self.played,
            "won": self.won,
            "drawn": self.drawn,
            "lost": self.lost,
            "goals_for": self.goals_for,
            "goals_against": self.goals_against,
            "goal_difference": self.goal_difference,
            "points": self.points,
        }


def league_table(matches: list[Match]) -> list[TableRow]:
    """Standings worked out from decided matches (3 for a win, 1 for a draw).

    A walkover or awarded match counts as a win and a loss with no goals.
    Ties are split on goal difference, then goals scored, then name. Teams
    that have not played yet are listed with zeros.
    """
    rows = {name: TableRow(name) for name in teams(matches)}
    for match in matches:
        if match.status not in DECIDED:
            continue
        for team in (match.home, match.away):
            row = rows[team]
            row.played += 1
            if (goals := match.goals(team)) is not None:
                row.goals_for += goals[0]
                row.goals_against += goals[1]
            outcome = match.outcome(team)
            if outcome == OUTCOME_WIN:
                row.won += 1
                row.points += POINTS_WIN
            elif outcome == OUTCOME_DRAW:
                row.drawn += 1
                row.points += POINTS_DRAW
            else:
                row.lost += 1
    ordered = sorted(
        rows.values(),
        key=lambda r: (-r.points, -r.goal_difference, -r.goals_for, r.team),
    )
    for position, row in enumerate(ordered, 1):
        row.position = position
    return ordered


@dataclass
class TeamView:
    """What the entities show for one team."""

    team: str
    matches: list[Match] = field(default_factory=list)  # the team's, by kick-off
    upcoming: list[Match] = field(default_factory=list)
    decided: list[Match] = field(default_factory=list)  # oldest first
    table: list[TableRow] = field(default_factory=list)
    row: TableRow | None = None
    division: list[Match] = field(default_factory=list)  # every match, by kick-off
    today: date | None = None  # UK date of the poll

    @property
    def next_match(self) -> Match | None:
        """The next match still to be played."""
        return self.upcoming[0] if self.upcoming else None

    @property
    def last_result(self) -> Match | None:
        """The most recent decided match."""
        return self.decided[-1] if self.decided else None

    def form(self, length: int = FORM_LENGTH) -> str:
        """Last results as letters, oldest first: 'WWDDW'."""
        return "".join(
            OUTCOME_LETTER[m.outcome(self.team)]  # type: ignore[index]
            for m in self.decided[-length:]
        )

    def matches_on(self, day: date) -> list[Match]:
        """Every match in the division on `day` (UK date), any status."""
        return [m for m in self.division if m.kickoff.date() == day]

    @property
    def latest_matchday(self) -> date | None:
        """The last day up to today with a decided match in the division."""
        days = [
            m.kickoff.date()
            for m in self.division
            if m.status in DECIDED
            and (self.today is None or m.kickoff.date() <= self.today)
        ]
        return max(days, default=None)


def team_view(
    all_matches: list[Match], team: str, now: datetime, played_grace: timedelta
) -> TeamView:
    """The team's matches, upcoming games, results and the table.

    A match stays upcoming until `played_grace` after kick-off, so the next
    match sensor does not jump ahead while the game is on; one without a
    kick-off time stays upcoming for the whole day.
    """

    def _not_over(match: Match) -> bool:
        if match.time_known:
            return match.kickoff + played_grace > now
        # No kick-off time: the match is on all day.
        return match.kickoff.date() >= now.astimezone(match.kickoff.tzinfo).date()

    mine = [m for m in all_matches if m.involves(team)]
    upcoming = [m for m in mine if m.status == STATUS_SCHEDULED and _not_over(m)]
    decided = [m for m in mine if m.status in DECIDED]
    table = league_table(all_matches)
    row = next((r for r in table if r.team == team), None)
    today = (
        now.astimezone(all_matches[0].kickoff.tzinfo).date() if all_matches else None
    )
    return TeamView(team, mine, upcoming, decided, table, row, all_matches, today)
