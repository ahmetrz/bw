"""Aggregate data/combine_log.jsonl into the two lookups engine/referee.py's board-context
needs (market gradeability, per-sport claimed-vs-realised), and the numbers the
performance-lab web pages show. Read-only over the existing log; writes nothing.

Reads data/combine_log.jsonl, not data/predictions.jsonl (docs/DECISIONS/0007): the
retired scanner's daily run was the only writer of predictions.jsonl, so once it was
deleted that file stopped growing — a track record silently frozen on the day the old
product was removed would be exactly the kind of stale-but-confident number hard rule 8
exists to catch, just aimed at this module instead of a pricing model. combine_log.jsonl
is a DIFFERENT shape (one row per DAY, each carrying a `legs` list, not one row per
selection), so `_load()` flattens each row's legs into the same per-selection shape the
aggregation functions below were written against — every leg becomes a record with
`sport_id`, `market_type`, `start`, `result` (None until tools/grade_combine.py settles
it) and `model_pct` (read from the leg's own `confidence.confidence_score`, the same 0-100
number engine/rating.py computed for it — hard rule 6 extended: this module is reporting
on that number after the fact, never recomputing a second one). A row that is already
flat (no `legs` key) passes through unchanged, which is what lets the test suite keep
constructing simple flat fixtures directly.
"""
import datetime
import json
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_LOG = os.path.join(ROOT, "data", "combine_log.jsonl")

MIN_MEANINGFUL = 20
DECIDED = ("win", "loss")           # push/half excluded from a hit-rate denominator,
                                     # same convention engine/grade.summarize() already uses
GRADEABLE_AFTER_HOURS = 48.0        # a prediction younger than this may simply not have
                                     # happened yet — not evidence the market is ungradeable


def _flatten(row):
    """One combine_log.jsonl row -> its legs, each shaped like a single predictions.jsonl
    record. A row with no `legs` key (a flat row already) passes through as-is."""
    if "legs" not in row:
        return [row]
    out = []
    for leg in row.get("legs") or []:
        conf = leg.get("confidence") or {}
        out.append({
            "sport_id": leg.get("sport_id"),
            "market_type": leg.get("market_type"),
            "start": leg.get("start"),
            "result": leg.get("result"),
            "model_pct": conf.get("confidence_score"),
        })
    return out


def _load(path):
    if not os.path.exists(path):
        return []
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            rows.extend(_flatten(row))
    return rows


def _age_hours(row, now):
    start = row.get("start")
    if not start:
        return None
    try:
        ts = datetime.datetime.fromisoformat(start.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (now - ts).total_seconds() / 3600.0


def market_history(path=None, now=None):
    """market_type -> {"graded": n, "ungradeable_rate": fraction}.

    "Ungradeable" = old enough to have almost certainly been played (>GRADEABLE_AFTER_HOURS
    past its start) and STILL has no result. A recent, merely-not-graded-yet prediction is
    not evidence against the market — only a stale, still-blank one is.
    """
    now = now or datetime.datetime.now(datetime.timezone.utc)
    rows = _load(path or DEFAULT_LOG)
    out = {}
    for r in rows:
        mt = r.get("market_type")
        if not mt:
            continue
        age = _age_hours(r, now)
        if age is None or age < GRADEABLE_AFTER_HOURS:
            continue
        bucket = out.setdefault(mt, {"old_enough": 0, "still_blank": 0})
        bucket["old_enough"] += 1
        if r.get("result") is None:
            bucket["still_blank"] += 1
    result = {}
    for mt, b in out.items():
        if b["old_enough"] < MIN_MEANINGFUL:
            continue
        result[mt] = {"graded": b["old_enough"],
                      "ungradeable_rate": round(b["still_blank"] / b["old_enough"], 3)}
    return result


def calibration_by_sport(path=None):
    """sport_id -> {"graded": n, "claimed": avg stated probability, "realised": hit rate}.

    Per-sport rather than per-odds-band — the granularity
    engine/referee.historical_performance_judge actually needs to decide whether to trust
    a NEW pick FOR THIS SPORT.
    """
    rows = _load(path or DEFAULT_LOG)
    by_sport = {}
    for r in rows:
        if r.get("result") not in DECIDED and r.get("result") != "push":
            continue
        if r.get("result") is None:
            continue
        sid = r.get("sport_id")
        by_sport.setdefault(sid, []).append(r)
    out = {}
    for sid, graded in by_sport.items():
        decided = [r for r in graded if r["result"] in DECIDED]
        if len(decided) < MIN_MEANINGFUL:
            continue
        wins = sum(1 for r in decided if r["result"] == "win")
        claimed = sum((r.get("model_pct") or r.get("score") or 0) / 100.0
                      for r in decided) / len(decided)
        out[sid] = {
            "graded": len(decided), "claimed": round(claimed, 4),
            "realised": round(wins / len(decided), 4),
        }
    return out


# The floor/ceiling any stated probability is clamped to before it is fed to log loss.
# An unclamped 100% claim that then loses scores negative infinity, which would let one
# graded selection dominate every other selection's evidence combined — exactly the kind
# of single-point fragility a calibration metric exists to catch, not to be broken by.
_EPS = 1e-4


def brier_score(path=None):
    """Mean squared error between stated probability and the 0/1 outcome, overall and by
    sport. Lower is better; 0.25 is what a constant 50% guess scores against a 50/50 coin.
    """
    rows = [r for r in _load(path or DEFAULT_LOG) if r.get("result") in DECIDED]
    if not rows:
        return None
    def _score(rs):
        if not rs:
            return None
        total = 0.0
        for r in rs:
            p = (r.get("model_pct") or r.get("score") or 0) / 100.0
            y = 1.0 if r["result"] == "win" else 0.0
            total += (p - y) ** 2
        return round(total / len(rs), 4)
    by_sport = {}
    for r in rows:
        by_sport.setdefault(r.get("sport_id"), []).append(r)
    return {"overall": _score(rows), "n": len(rows),
           "by_sport": {sid: _score(rs) for sid, rs in by_sport.items()}}


def log_loss(path=None):
    """Mean negative log-likelihood of the stated probability against the outcome.
    Lower is better; ln(2)≈0.693 is what a constant 50% guess scores."""
    rows = [r for r in _load(path or DEFAULT_LOG) if r.get("result") in DECIDED]
    if not rows:
        return None
    total = 0.0
    for r in rows:
        p = min(max((r.get("model_pct") or r.get("score") or 0) / 100.0, _EPS), 1 - _EPS)
        y = 1.0 if r["result"] == "win" else 0.0
        total += -(y * math.log(p) + (1 - y) * math.log(1 - p))
    return round(total / len(rows), 4)
