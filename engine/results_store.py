"""One results table per sport, in ONE shape, whatever the source was.

    data/results/<sport_id>.jsonl
    {"date": "2026-05-24", "home": "...", "away": "...",
     "home_score": 92, "away_score": 85, "league": "...", "source": "euroleague"}

THIS FILE EXISTS BECAUSE THE OLD APPROACH DOES NOT SCALE. Football, table tennis and
basketball each got a bespoke harvester, a bespoke model, a bespoke probability function
and a bespoke calibration. Three sports cost three of everything, and the book carries 47
with fixtures inside 48 hours. At that rate the product never covers its own card, and
each new sport is also a new way to be wrong — basketball's sign error and table tennis's
extrapolation were both bugs that only existed because the maths had been written again.

So the shape is fixed here and nothing downstream is allowed to care where a row came
from. An adapter's whole job is to produce these five fields. `engine/model_generic.py`
then fits ANY sport from this table with no sport-specific code at all, which is what
makes the next sport cheap instead of another week.

Deliberately NOT stored: markets, odds, or anything the book said. This is a record of
what happened, and it stays that way — the moment a price enters this table it can leak
into a model, and direction must never come from the price.
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE = os.path.join(ROOT, "data", "results")

REQUIRED = ("date", "home", "away", "home_score", "away_score")


def path(sport_id):
    return os.path.join(STORE, f"{int(sport_id)}.jsonl")


def clean(row):
    """A row that is missing anything, or carries a non-numeric score, is not a result.

    Returned as None rather than repaired. A half-known result is how a model quietly
    learns from a fixture that never finished.
    """
    if not row:
        return None
    out = {}
    for k in REQUIRED:
        if row.get(k) is None:
            return None
    try:
        out["home_score"] = int(row["home_score"])
        out["away_score"] = int(row["away_score"])
    except (TypeError, ValueError):
        return None
    for k in ("date", "home", "away"):
        v = str(row[k]).strip()
        if not v:
            return None
        out[k] = v
    out["date"] = out["date"][:10]
    # A STABLE ID when the source has one. This is what stops a club's history being
    # split across its sponsor names: EuroLeague's club code and Setka's player id both
    # survive a rename, and a name never does. Optional, because most sources have none.
    for k in ("home_id", "away_id"):
        if row.get(k) not in (None, ""):
            out[k] = str(row[k])
    # RATING POOL: the set of teams whose ratings are on one scale because they actually
    # play each other. Football divisions never meet, so a League Two 1500 and a Premier
    # League 1500 are not the same strength; EuroLeague and EuroCup clubs move between
    # competitions from season to season, so they ARE one scale. The adapter knows which
    # of those two situations its sport is in, and says so. Absent means one pool.
    if row.get("pool") not in (None, ""):
        out["pool"] = str(row["pool"])
    # WHAT THE SCORE COUNTS. Goals, points, runs or sets — and it is not decoration: the
    # book's "total 76.5" is a POINTS market, and pricing it from a distribution of SETS
    # says "under 76.5" is certain, because the sets recorded here never exceed 5. That is
    # exactly what happened, at 100.00% on a 1.79 shot. A distribution only answers
    # questions asked in its own unit.
    if row.get("unit"):
        out["unit"] = str(row["unit"])
    # SURFACE: a rating-relevant attribute for sports where it matters (tennis: clay/
    # grass/hard specialists diverge 100-200 Elo points from their overall rating per
    # research/tennis.json). Optional and sport-specific, same treatment as "pool" — an
    # adapter that has it says so, and nothing downstream may assume it exists.
    if row.get("surface"):
        out["surface"] = str(row["surface"])
    for k in ("league", "source", "season", "neutral", "extra_periods"):
        if row.get(k) is not None:
            out[k] = row[k]
    return out


def key(row):
    """Identity of a result: the two names on a date. One fixture, one row."""
    return (row["date"], row["home"], row["away"])


def load(sport_id):
    rows, p = [], path(sport_id)
    if not os.path.exists(p):
        return rows
    with open(p) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def save(sport_id, rows):
    os.makedirs(STORE, exist_ok=True)
    rows = sorted(rows, key=lambda r: (r["date"], r["home"], r["away"]))
    with open(path(sport_id), "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(rows)


def merge(sport_id, incoming):
    """Add what is new, keep what is there. Returns (added, total).

    Idempotent on purpose: a collector is going to be re-run on overlapping windows for
    the rest of this project's life, and re-running one must never duplicate a match or
    double-count it into a rating.
    """
    have = {key(r): r for r in load(sport_id)}
    added = 0
    for raw in incoming:
        row = clean(raw)
        if not row:
            continue
        k = key(row)
        if k in have:
            continue
        have[k] = row
        added += 1
    return added, save(sport_id, list(have.values()))


def restate(sport_id, incoming):
    """Let an adapter's CURRENT output replace the rows it wrote before. Returns (n, total).

    `merge` deliberately never overwrites, because a collector re-running on an
    overlapping window must not rewrite history. The cost of that rule shows up when an
    adapter learns to declare something new: `unit` and then `pool` were both added after
    tens of thousands of rows had already been stored without them, so the declaration
    reached only rows collected afterwards and the archive sat in a nameless pool that the
    live watcher's rows could never join.

    This is the deliberate, explicit way out. It rewrites ONLY the rows this adapter
    produces now, leaves every other source's rows in the same file alone, and re-derives
    nothing — it is the same adapter reading the same source, so the scores are the scores.
    """
    have = {key(r): r for r in load(sport_id)}
    changed = 0
    for raw in incoming:
        row = clean(raw)
        if not row:
            continue
        k = key(row)
        if have.get(k) != row:
            changed += 1
        have[k] = row
    return changed, save(sport_id, list(have.values()))


def summary():
    """What we hold, per sport — the number that says how far coverage actually goes."""
    out = {}
    if not os.path.isdir(STORE):
        return out
    for name in sorted(os.listdir(STORE)):
        if not name.endswith(".jsonl"):
            continue
        sid = int(name[:-6])
        rows = load(sid)
        if not rows:
            continue
        teams = {r["home"] for r in rows} | {r["away"] for r in rows}
        out[sid] = {
            "games": len(rows),
            "teams": len(teams),
            "first": min(r["date"] for r in rows),
            "last": max(r["date"] for r in rows),
            "sources": sorted({r.get("source") or "?" for r in rows}),
        }
    return out
