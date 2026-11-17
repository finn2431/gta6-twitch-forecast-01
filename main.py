"""gta6-twitch-ccu-forecast-01 entry: forecast a launch day's Twitch viewers hour by hour.

For a case we see the category's hour-1 print and a set of past launch comparables with their
hourly counts.  Each comparable is turned into a launch *shape* (log viewers of each release-day
hour 2..24 minus log viewers of its own hour 1), the shapes are averaged with a weighted median,
and the weighted spread of the residuals around that centre gives the quantiles.  A small random
walk widening keeps the later hours honest.

The program is standard library only, deterministic (no randomness, no clock, no network), reads
every ``*.in`` in $MAKEFUN_INPUT_DIR (default /input) and writes ``<id>.out`` to
$MAKEFUN_OUTPUT_DIR (default /output).

Run locally:

    mkdir -p out
    MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
"""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path

# Quantile levels, in the order each output row lists them.
LEVELS = (0.05, 0.25, 0.5, 0.75, 0.95)
# Standard normal quantiles at those levels.
Z = (-1.645, -0.674, 0.0, 0.674, 1.645)

# Move each residual quantile outward/inward by this factor before adding it to the centre.
SPREAD = 0.75
# Random-walk widening in log space per sqrt(hour - 1).
WIDEN = 0.05
# Recency decay: a launch this many years older than the case gets exp(-1) of the weight.
RECENCY_SCALE = 8.0
# An extended-look premiere of the case's own game is not a launch day, so it counts less.
OWN_GAME_WEIGHT = 0.35
# Fallback when too few comparables cover an hour: flat hour 1 with this log spread.
FALLBACK_SIGMA = 0.15
# Below this many comparable shapes for an hour, use the fallback.
MIN_COMPARABLES = 4

# Words that may follow the game's name in a comparable's label when that comparable is the
# case's own game rather than a different launch (e.g. "<game> category before release ...").
_OWN_SUFFIX_WORDS = frozenset(
    {"category", "categories", "before", "own", "history", "release", "premiere", "onward", "game", "twitch"}
)

_TIMESTAMP = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})"
    r"(?::(\d{2})(?:\.(\d{1,9}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def days_from_civil(year: int, month: int, day: int) -> int:
    """Days since 1970-01-01 for a proleptic Gregorian date (Howard Hinnant's algorithm)."""
    y = year - (1 if month <= 2 else 0)
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    mp = (month + 9) % 12  # March = 0
    doy = (153 * mp + 2) // 5 + day - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def parse_timestamp(text: str) -> float:
    """Parse an ISO 8601 timestamp into seconds since the Unix epoch (UTC).

    Handles ``2026-11-19T00:00:00Z``, ``...T00:00:00+02:00`` and fractional seconds.  Written
    by hand so the program needs no zoneinfo, dateutil or platform timezone database.
    """
    match = _TIMESTAMP.match(str(text).strip())
    if match is None:
        raise ValueError(f"cannot parse timestamp {text!r}")
    year, month, day, hour, minute = (int(match.group(i)) for i in range(1, 6))
    second = int(match.group(6) or 0)
    fraction = float("0." + match.group(7)) if match.group(7) else 0.0
    zone = match.group(8)
    offset = 0
    if zone and zone not in ("Z", "z"):
        sign = 1 if zone[0] == "+" else -1
        body = zone[1:].replace(":", "")
        offset = sign * (int(body[:2]) * 3600 + int(body[2:]) * 60)
    return days_from_civil(year, month, day) * 86400.0 + hour * 3600.0 + minute * 60.0 + second + fraction - offset


def hour_offset(from_text: str, day_start: str) -> int:
    """Whole hours between a comparable's release-day start and one of its points."""
    delta = parse_timestamp(from_text) - parse_timestamp(day_start)
    return int(round(delta / 3600.0))


def year_of(timestamp: str) -> int:
    """The calendar year a timestamp's text names (all case timestamps are ISO 8601)."""
    return int(str(timestamp).strip()[:4])


def _norm(text: object) -> str:
    return " ".join(str(text).lower().split())


def is_own_game(game_name: object, comparable_name: object) -> bool:
    """Whether a comparable is the case's own game rather than a different launch."""
    game = _norm(game_name)
    name = _norm(comparable_name)
    if not game or not name:
        return False
    if name == game:
        return True
    if not name.startswith(game + " "):
        return False
    token = name[len(game) + 1 :].split()[0].strip("(-:,.")
    return token in _OWN_SUFFIX_WORDS


def index_comparable(comparable: dict) -> dict | None:
    """Reduce a comparable to its label, year and hour-offset -> viewers map."""
    hourly = comparable.get("hourly")
    day_start = comparable.get("day_start")
    if not hourly or not day_start:
        return None
    by_hour: dict[int, float] = {}
    try:
        for point in hourly:
            if point.get("from") is None:
                continue
            by_hour[hour_offset(point["from"], day_start)] = point.get("viewers")
    except (KeyError, TypeError, ValueError):
        return None
    return {
        "name": str(comparable.get("name", "")),
        "day_start": day_start,
        "year": year_of(day_start),
        "by_hour": by_hour,
    }


def build_shapes(
    case_hour1: float,
    reference_year: int,
    game_name: object,
    comparables: list[dict],
) -> dict[int, list[tuple[float, float]]]:
    """For every hour 2..24, the comparable log shapes and their weights."""
    shapes: dict[int, list[tuple[float, float]]] = {hour: [] for hour in range(2, 25)}
    base = math.log(max(1.0, float(case_hour1)))
    for comparable in comparables:
        hours = comparable["by_hour"]
        first = hours.get(0)
        if first is None:
            continue
        try:
            first = float(first)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(first) or first <= 0.0:
            continue
        weight = math.exp(-abs(math.log(first) - base))
        weight *= math.exp(-(reference_year - comparable["year"]) / RECENCY_SCALE)
        if is_own_game(game_name, comparable["name"]):
            weight *= OWN_GAME_WEIGHT
        if not math.isfinite(weight) or weight <= 0.0:
            continue
        log_first = math.log(first)
        for hour in range(2, 25):
            viewers = hours.get(hour - 1)
            try:
                viewers = float(viewers)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(viewers) or viewers <= 0.0:
                continue
            shapes[hour].append((math.log(viewers) - log_first, weight))
    return shapes


def weighted_quantile(pairs: list[tuple[float, float]], tau: float) -> float:
    """The weighted quantile at ``tau`` of (value, weight) pairs."""
    ordered = sorted(pairs, key=lambda pair: pair[0])
    total = math.fsum(weight for _, weight in ordered)
    if total <= 0.0:
        return ordered[len(ordered) // 2][0]
    target = tau * total
    cumulative = 0.0
    for value, weight in ordered:
        cumulative += weight
        if cumulative >= target:
            return value
    return ordered[-1][0]


def finish_quantiles(values: list[float]) -> list[float]:
    """Clamp to the contest's bounds, round, and force the row to be non-decreasing."""
    row: list[float] = []
    for value in values:
        if not math.isfinite(value):
            value = 1.0
        value = min(max(value, 0.000001), 1_000_000_000.0)
        value = round(value, 6)
        if value <= 0.0:
            value = 0.000001
        if value > 1_000_000_000.0:
            value = 1_000_000_000.0
        if row and value < row[-1]:
            value = row[-1]
        row.append(value)
    return row


def forecast_hour(p1: float, hour: int, pairs: list[tuple[float, float]]) -> list[float]:
    """Five quantiles for one hour from the comparable shapes."""
    root = math.sqrt(hour - 1)
    if len(pairs) < MIN_COMPARABLES:
        return finish_quantiles([p1 * math.exp(z * FALLBACK_SIGMA * root) for z in Z])
    centre = weighted_quantile(pairs, 0.5)
    residuals = [(shape - centre, weight) for shape, weight in pairs]
    values = [
        p1 * math.exp(centre + SPREAD * weighted_quantile(residuals, tau) + z * WIDEN * root)
        for tau, z in zip(LEVELS, Z)
    ]
    return finish_quantiles(values)


def forecast_case(case: dict) -> dict:
    """Build the 23 output rows for one case object."""
    first = next((row for row in case.get("known", []) if int(row.get("hour", 0)) == 1), None)
    try:
        p1 = float(first["viewers"]) if first is not None else 1.0
    except (KeyError, TypeError, ValueError):
        p1 = 1.0
    if not math.isfinite(p1) or p1 <= 0.0:
        p1 = 1.0
    day_start = case.get("day_start", "")
    reference_year = year_of(day_start) if day_start else 1970
    game_name = (case.get("game") or {}).get("name", "")
    indexed = [index_comparable(c) for c in case.get("comparables", [])]
    shapes = build_shapes(p1, reference_year, game_name, [c for c in indexed if c is not None])
    return {"hours": [{"hour": hour, "q": forecast_hour(p1, hour, shapes[hour])} for hour in range(2, 25)]}


def main() -> None:
    input_dir = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
    output_dir = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))
    output_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(input_dir.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case)
        text = json.dumps(forecast, separators=(",", ":"), allow_nan=False) + "\n"
        (output_dir / f"{path.stem}.out").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
