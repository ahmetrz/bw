"""Ranked table + JSON writer + book-mismatch warning."""
import json


def warn_book(requested, found):
    """Loud warning if the loaded data is not the requested book (the isSample pattern)."""
    if requested in found:
        return
    print("=" * 68)
    print("  ⚠  BOOK MISMATCH")
    print(f"  requested : {requested}")
    print(f"  found     : {', '.join(sorted(found)) or '<none>'}")
    print("  The output below is NOT Betwinner. Do not trust it.")
    print("  Re-check the fetch: this is almost certainly a cached/wrong pull.")
    print("=" * 68)


def _short(sel, n=20):
    sel = sel or ""
    return sel if len(sel) <= n else sel[: n - 1] + "…"


def print_table(rows, top_n):
    rows = rows[:top_n]
    if not rows:
        print("No selections passed the filters (all closed / stale / no valid market).")
        return
    limit_live = rows[0].get("limit_score") is not None
    print(f"{'#':>3} {'match':>13} {'type':<10} {'selection':<20} "
          f"{'odds':>6} {'hold%':>6} {'limit':>7} {'stale_s':>8} {'score':>6}")
    print("-" * 92)
    for i, r in enumerate(rows, 1):
        match = f"{r['p1']}v{r['p2']}"
        limit = r["limit"] if (limit_live and r["limit"] is not None) else "-"
        stale = int(r["staleness_seconds"]) if r["staleness_seconds"] is not None else "-"
        print(f"{i:>3} {match:>13} {r['market_type']:<10} {_short(r['selection']):<20} "
              f"{r['odds']:>6.2f} {r['overround']*100:>6.2f} {str(limit):>7} "
              f"{str(stale):>8} {r['total_score']:>6.3f}")


def write_json(rows, top_n, path):
    out = []
    for r in rows[:top_n]:
        out.append({
            "fixture_id": r["fixture_id"],
            "match": f"{r['p1']} v {r['p2']}",
            "start": r["start"],
            "market_type": r["market_type"],
            "main_line": r["main_line"],
            "selection": r["selection"],
            "odds": r["odds"],
            "implied_prob": round(r["implied"], 4),
            "market_overround": round(r["overround"], 4),
            "limit": r["limit"],
            "staleness_seconds": r["staleness_seconds"],
            "margin_score": r["margin_score"],
            "limit_score": r["limit_score"],
            "range_score": r["range_score"],
            "total_score": r["total_score"],
            "flags": r["flags"],
        })
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nWrote {len(out)} selections to {path}")


def parlay_summary(rows, top_n):
    """Single-book parlay described in the book's OWN implied numbers. Not value."""
    legs = rows[:top_n]
    if not legs:
        print("No legs to combine.")
        return
    combined_odds = 1.0
    combined_fair = 1.0
    exp_return = 1.0
    for r in legs:
        combined_odds *= r["odds"]
        fair = r["implied"] / (1.0 + r["overround"])   # book-fair prob for this selection
        combined_fair *= fair
        exp_return *= (1.0 / (1.0 + r["overround"]))    # per-leg book expected-return factor
    print("\n" + "=" * 68)
    print(f"  PARLAY of top {len(legs)} legs  (Betwinner's own numbers — NOT value)")
    print(f"  combined decimal odds        : {combined_odds:,.2f}")
    print(f"  combined book-implied prob   : {combined_fair:.3e}")
    print(f"  book expected-return multiple: {exp_return:.4f}  (<1; worse per leg)")
    print("  A single book cannot yield positive expectation on its own line.")
    print("  Also subject to Betwinner's per-slip payout cap.")
    print("=" * 68)
