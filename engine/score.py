"""Hard filters + composite score. Single-book, no reference."""
from datetime import timedelta
import config


def _overrounds(rows):
    """Per-market hold, only for markets with >=2 outcomes.

    The hold is sum(implied)/coverage - 1, not sum(implied) - 1. Coverage is how many
    times a market's selections cover the outcome space, and it is 1 for almost every
    market — but not for double chance, whose 1X, 12 and X2 each contain two of the three
    results and therefore sum to about 2 under fair pricing. Treating that sum as a hold
    reported every double-chance market at 100%+, which MAX_OVERROUND then discarded, and
    since double chance is the top rung of the football safety ladder the ladder had
    nothing to select. The measured sum on the sample was 2.154 — a 7.7% hold.
    """
    agg, counts, cover = {}, {}, {}
    for r in rows:
        k = r["market_key"]
        agg[k] = agg.get(k, 0.0) + r["implied"]
        counts[k] = counts.get(k, 0) + 1
        cover[k] = r.get("market_coverage") or 1
    out = {}
    for k, s in agg.items():
        fair = s / cover[k]
        out[k] = (fair - 1.0) if (counts[k] >= 2 and fair > 1.0) else None
    return out


def overrounds(rows):
    """Per-market hold for a set of rows, keyed by market_key.

    Public because the ladder path needs it: selections there are chosen from UNFILTERED
    rows (every plus-handicap and every non-headline total is an alt line), so they never
    pass through filter_and_score and would otherwise carry no hold at all.
    """
    return _overrounds(rows)


def _staleness_seconds(rows):
    """Relative to the freshest line in the pull, so saved fixtures still filter."""
    times = [r["changed_at"] for r in rows if r["changed_at"]]
    if not times:
        return {id(r): None for r in rows}
    ref = max(times)
    return {id(r): (ref - r["changed_at"]).total_seconds() if r["changed_at"] else None
            for r in rows}


def _norm(vals, lo_pct=0.0, hi_pct=0.90):
    """Normalize against a percentile ceiling rather than the raw maximum.

    Min-max is destroyed by exotics. In the first real Betwinner pull the market holds
    ran 4.67% to 233.9% — 109 markets over 100% (correct-score and similar). Scaling by
    that max squeezed every ordinary market into 0.95-1.00: a 6.4% hold and a 15% hold
    landed 0.037 apart, so every emitted score printed as 1.000 and the ranking carried
    no information.

    The outliers are one-sided — always a huge hold, never a tiny one — so only the
    upper bound needs robustifying. The lower bound stays at the true minimum because
    the cheapest markets are precisely what the scan exists to surface; clipping there
    would tie the whole top of the ranking. Callers clamp, so values past the ceiling
    pin to 0.
    """
    xs = sorted(v for v in vals if v is not None)
    if not xs:
        return None

    def pct(p):
        return xs[min(len(xs) - 1, max(0, int(round(p * (len(xs) - 1)))))]

    lo, hi = pct(lo_pct), pct(hi_pct)
    if hi == lo:
        return {"lo": lo, "hi": hi, "flat": True}
    return {"lo": lo, "hi": hi, "flat": False}


def _clamp01(x):
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


def _norms_by_type(kept, global_norm):
    """One margin scale per market type, falling back to the global scale.

    A totals hold and a 1X2 hold are not the same measurement. On the first real pull
    every totals market was cheaper than every moneyline market, so one shared scale
    made the ranking a market-type sort — the top 50 was 100% totals under every
    weighting tried. Scaling each type against itself asks the question that can
    actually be answered from a single book: how cheap is this market for its kind.

    A type with too few markets is not normalized against itself: its scale would be
    flat or near-flat and hand every one of its selections a perfect margin score.
    """
    if not getattr(config, "MARGIN_NORM_PER_TYPE", False):
        return {}
    floor = getattr(config, "MIN_MARKETS_PER_TYPE", 5)
    markets_by_type = {}
    for r in kept:
        markets_by_type.setdefault(r["market_type"], {})[r["market_key"]] = r["overround"]
    out = {}
    for mtype, markets in markets_by_type.items():
        if len(markets) < floor:
            out[mtype] = global_norm
            continue
        nrm = _norm(list(markets.values()))
        out[mtype] = nrm if nrm and not nrm["flat"] else global_norm
    return out


def _range_score(odds):
    lo, hi = config.ODDS_RANGE
    if lo <= odds <= hi:
        return 1.0
    d = (lo - odds) if odds < lo else (odds - hi)
    return max(0.0, 1.0 - d / max(config.RANGE_DECAY, 1e-9))


def filter_and_score(rows):
    over = _overrounds(rows)
    stale = _staleness_seconds(rows)
    window = config.STALENESS_MINUTES * 60

    # --- hard filters ---
    excluded = getattr(config, "EXCLUDED_SPORTS", set())
    kept = []
    for r in rows:
        if not (r["active"] and r["market_active"]):
            continue
        # Dropped before scoring, not after: these sports are cheap enough to distort the
        # normalization itself, so letting them through and filtering the table later
        # would still move every other row's margin_score. See config.EXCLUDED_SPORTS.
        if excluded and r.get("sport_id") in excluded:
            continue
        s = stale[id(r)]
        if s is not None and s > window:
            continue
        if not config.INCLUDE_ALT_LINES and r["is_alt"]:
            continue
        if config.ALLOWED_MARKET_TYPES and r["market_type"] not in config.ALLOWED_MARKET_TYPES:
            continue
        r["overround"] = over.get(r["market_key"])
        if r["overround"] is None:
            continue  # can't score margin without a valid two+ sided market
        max_ov = getattr(config, "MAX_OVERROUND", None)
        if max_ov is not None and r["overround"] > max_ov:
            continue
        r["staleness_seconds"] = s
        kept.append(r)

    if not kept:
        return []

    # --- component normalization ---
    # margin: lower overround -> higher score. Normalized over DISTINCT MARKETS, not
    # rows: the hold is a per-market quantity, so scaling it against a row-weighted
    # distribution counts each market once per outcome. Exotics carry dozens of
    # outcomes each, which is exactly how they swamped the scale before.
    ov_norm = _norm(list({r["market_key"]: r["overround"] for r in kept}.values()))
    ov_norms_by_type = _norms_by_type(kept, ov_norm)
    limits = [r["limit"] for r in kept if r["limit"] is not None]
    limit_live = len(limits) > 0
    lim_norm = _norm([r["limit"] for r in kept]) if limit_live else None

    # weights, with limit redistributed if absent
    w = dict(config.WEIGHTS)
    if not limit_live:
        dropped = w.pop("limit", 0.0)
        tot = sum(w.values()) or 1.0
        for k in w:
            w[k] += dropped * (w[k] / tot)
    else:
        w.setdefault("limit", 0.0)

    for r in kept:
        # margin_score, scaled against this market's own type where that is meaningful
        nrm = ov_norms_by_type.get(r["market_type"], ov_norm)
        if nrm["flat"]:
            ms = 1.0
        else:
            ms = _clamp01(
                1.0 - (r["overround"] - nrm["lo"]) / (nrm["hi"] - nrm["lo"])
            )
        # limit_score
        if limit_live and r["limit"] is not None and not lim_norm["flat"]:
            ls = _clamp01(
                (r["limit"] - lim_norm["lo"]) / (lim_norm["hi"] - lim_norm["lo"])
            )
        elif limit_live and r["limit"] is not None:
            ls = 1.0
        else:
            ls = 0.0
        # range_score
        rs = _range_score(r["odds"])

        r["margin_score"] = round(ms, 4)
        r["limit_score"] = round(ls, 4) if limit_live else None
        r["range_score"] = round(rs, 4)
        r["total_score"] = round(
            w.get("margin", 0) * ms + w.get("limit", 0) * ls + w.get("range", 0) * rs, 4
        )
        r["flags"] = []
        if not limit_live:
            r["flags"].append("no_limit_data")
        if r["is_alt"]:
            r["flags"].append("alt_line")

    kept.sort(key=lambda r: r["total_score"], reverse=True)
    return _diversify(kept)


def _diversify(rows):
    """Cap how many selections one fixture contributes, preserving score order.

    Every market inside a fixture shares roughly that fixture's hold, so the margin
    component alone will stack one match's whole ladder at the top — the first real
    Betwinner run returned a top 24 drawn entirely from a single fixture, which is the
    failure mode CLAUDE.md's first-run sanity check is there to catch.

    Capped rows are not discarded: they are appended after the capped ranking, so the
    ordering changes but nothing silently vanishes from report.json.
    """
    cap = getattr(config, "MAX_PER_FIXTURE", 0)
    if not cap:
        return rows
    seen, primary, overflow = {}, [], []
    for r in rows:
        # Same reason as the parlay: cap per real match, not per game id.
        fid = r.get("match_id", r["fixture_id"])
        seen[fid] = seen.get(fid, 0) + 1
        if seen[fid] <= cap:
            primary.append(r)
        else:
            r["flags"].append("fixture_cap")
            overflow.append(r)
    return primary + overflow
