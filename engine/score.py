"""Hard filters + composite score. Single-book, no reference."""
from datetime import timedelta
import config


def _overrounds(rows):
    """Per-market hold: sum(implied) - 1, only for markets with >=2 outcomes and sum>1."""
    agg = {}
    for r in rows:
        agg.setdefault(r["market_key"], 0.0)
        agg[r["market_key"]] += r["implied"]
    counts = {}
    for r in rows:
        counts[r["market_key"]] = counts.get(r["market_key"], 0) + 1
    out = {}
    for k, s in agg.items():
        out[k] = (s - 1.0) if (counts[k] >= 2 and s > 1.0) else None
    return out


def _staleness_seconds(rows):
    """Relative to the freshest line in the pull, so saved fixtures still filter."""
    times = [r["changed_at"] for r in rows if r["changed_at"]]
    if not times:
        return {id(r): None for r in rows}
    ref = max(times)
    return {id(r): (ref - r["changed_at"]).total_seconds() if r["changed_at"] else None
            for r in rows}


def _norm(vals):
    xs = [v for v in vals if v is not None]
    if not xs:
        return None
    lo, hi = min(xs), max(xs)
    if hi == lo:
        return {"lo": lo, "hi": hi, "flat": True}
    return {"lo": lo, "hi": hi, "flat": False}


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
    kept = []
    for r in rows:
        if not (r["active"] and r["market_active"]):
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
        r["staleness_seconds"] = s
        kept.append(r)

    if not kept:
        return []

    # --- component normalization ---
    # margin: lower overround -> higher score
    ov_norm = _norm([r["overround"] for r in kept])
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
        # margin_score
        if ov_norm["flat"]:
            ms = 1.0
        else:
            ms = 1.0 - (r["overround"] - ov_norm["lo"]) / (ov_norm["hi"] - ov_norm["lo"])
        # limit_score
        if limit_live and r["limit"] is not None and not lim_norm["flat"]:
            ls = (r["limit"] - lim_norm["lo"]) / (lim_norm["hi"] - lim_norm["lo"])
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
    return kept
