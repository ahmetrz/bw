"""Attach model-vs-book edge to scored rows.

    edge = model_probability * decimal_odds - 1

A positive number says the model thinks the price is too long. Read the warning below
before acting on one.

WHAT A POSITIVE EDGE ACTUALLY MEANS HERE
Betwinner prices thousands of markets with paid data, traders and live exposure. A free
public model does not beat that by default, so most positive edges this computes are
model error, not mispricing — and the errors concentrate exactly where the model is
weakest, which is also where it disagrees most. That is the trap: sorting by edge sorts
by disagreement, and disagreement correlates with the model being wrong.

None of this is calibrated yet. Nothing here has been backtested against settled
results, so `edge` is a research signal, not a betting instruction. `config.WEIGHTS`
leaves it out until that work is done.
"""
import config
from engine import model_football

# Which sports have a model. Betwinner sport id 1 is football.
MODELLED_SPORTS = {1}


def annotate(rows, index=None, min_name_score=0.82):
    """Add model_prob, edge and match quality to every row we can map.

    Rows the model cannot reach keep `edge = None`. That is deliberate: an unmodelled
    row must not be silently treated as a zero-edge row, or the ranking would quietly
    prefer whatever the model happens to cover.
    """
    # Sub-games are excluded outright. The model produces full-match probabilities, so
    # applying them to a half or a corners market is not an approximation, it is wrong —
    # it was generating edges above +1.0 before this was caught.
    football = [r for r in rows
                if r.get("sport_id") in MODELLED_SPORTS and not r.get("sub_game")]
    if not football:
        return {"modelled": 0, "matched_fixtures": 0, "priced": 0}

    if index is None:
        try:
            index = model_football.build_index()
        except Exception as e:  # network is optional; the scan still works without it
            print(f"  (model unavailable: {e})")
            return {"modelled": 0, "matched_fixtures": 0, "priced": 0, "error": str(e)}

    # Resolve each fixture once, not once per selection.
    by_fixture = {}
    for r in football:
        by_fixture.setdefault(r["fixture_id"], r)
    resolved = {}
    for fid, sample in by_fixture.items():
        probs, score = model_football.lookup(
            index, sample.get("p1"), sample.get("p2"), cutoff=min_name_score
        )
        if probs and score >= min_name_score:
            resolved[fid] = (probs, score)

    priced = 0
    for r in football:
        got = resolved.get(r["fixture_id"])
        if not got:
            continue
        probs, name_score = got
        p = model_football.model_prob(r, probs)
        if p is None or p <= 0.0:
            continue
        r["model_prob"] = round(p, 4)
        r["name_match"] = round(name_score, 3)
        r["edge"] = round(p * r["odds"] - 1.0, 4)
        r["flags"].append("modelled")
        priced += 1

    return {
        "modelled": len(football),
        "matched_fixtures": len(resolved),
        "total_fixtures": len(by_fixture),
        "priced": priced,
    }


def summarize(rows):
    """Distribution of computed edges — the sanity check on the model, not on the book.

    A model that agrees with a sharp book produces edges clustered near zero. A wide
    spread means the model disagrees a lot, which is far more likely to be the model's
    problem than the book's.
    """
    e = sorted(r["edge"] for r in rows if r.get("edge") is not None)
    if not e:
        return None
    n = len(e)
    q = lambda p: e[min(n - 1, max(0, int(p * (n - 1))))]  # noqa: E731
    return {
        "n": n,
        "min": e[0], "p25": q(0.25), "median": q(0.5), "p75": q(0.75), "max": e[-1],
        "positive": sum(1 for x in e if x > 0),
        "positive_pct": 100.0 * sum(1 for x in e if x > 0) / n,
    }
