"""OddsPapi odds-by-tournaments response -> normalized selection rows.

Book-agnostic: works for any bookmaker slug the API returns.
"""
from datetime import datetime, timezone


def _market_type(bmid: str) -> str:
    s = bmid or ""
    for t in ("moneyline", "teamTotal", "totals", "spreads"):
        if t in s:
            return t
    return "other"


def _is_alt(bmid: str) -> bool:
    return (bmid or "").startswith("altLine")


def _parse_ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def books_in(data) -> set:
    """Which bookmaker slugs actually appear in the payload."""
    out = set()
    for fx in data:
        out.update((fx.get("bookmakerOdds") or {}).keys())
    return out


def normalize(data, book):
    """Yield one dict per selection for `book`. market_key groups a market's outcomes."""
    rows = []
    for fx in data:
        b = (fx.get("bookmakerOdds") or {}).get(book)
        if not b:
            continue
        fxid = fx.get("fixtureId")
        for mid, md in (b.get("markets") or {}).items():
            bmid = md.get("bookmakerMarketId") or ""
            mtype = _market_type(bmid)
            is_alt = _is_alt(bmid)
            m_active = bool(md.get("marketActive"))
            for oid, od in (md.get("outcomes") or {}).items():
                pl = (od.get("players") or {}).get("0")
                if not pl:
                    continue
                price = pl.get("price")
                if not price or price <= 1.0:
                    continue
                rows.append({
                    "fixture_id": fxid,
                    "p1": fx.get("participant1Id"),
                    "p2": fx.get("participant2Id"),
                    "start": fx.get("startTime"),
                    "market_key": (fxid, mid),
                    "market_type": mtype,
                    "is_alt": is_alt,
                    "main_line": bool(pl.get("mainLine")),
                    "selection": pl.get("bookmakerOutcomeId"),
                    "odds": float(price),
                    "implied": 1.0 / float(price),
                    "active": bool(pl.get("active")),
                    "market_active": m_active,
                    "limit": pl.get("limit"),
                    "changed_at": _parse_ts(pl.get("changedAt")),
                })
    return rows
