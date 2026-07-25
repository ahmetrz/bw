"""Single-book parlay construction, described only in Betwinner's own numbers.

CLAUDE.md hard rule 4: a parlay inside one book cannot carry positive expectation, and
this module must never present it as if it could. `summarize` returns the three figures
that rule requires — combined decimal odds, combined book-implied probability, and the
book expected-return multiple — so callers can display them together with the payout-cap
caveat.

The arithmetic, stated plainly: each leg multiplies the book's margin in again. At the
7.14% median hold measured on real Betwinner data, one leg returns 0.9334 of stake in
expectation and fifty legs return 0.9334^50 = 0.032. That is a 96.8% expected loss, and
no choice of legs changes it — only the number of legs does.
"""
import config


def build(rows, legs=50, min_odds=1.10, max_odds=None):
    """Pick at most one selection per fixture, best score first.

    One-per-fixture is not a preference, it is a correctness requirement: two selections
    from the same match are not independent, and books reject most such combinations on
    the slip anyway.
    """
    picked, seen = [], set()
    for r in rows:
        if len(picked) >= legs:
            break
        if r["fixture_id"] in seen:
            continue
        if r["odds"] < min_odds:
            continue
        if max_odds is not None and r["odds"] > max_odds:
            continue
        seen.add(r["fixture_id"])
        picked.append(r)
    return picked


def summarize(legs):
    """The figures CLAUDE.md hard rule 4 requires. None of them is a value claim."""
    if not legs:
        return None
    combined_odds = 1.0
    combined_fair = 1.0
    exp_return = 1.0
    for r in legs:
        combined_odds *= r["odds"]
        # The book's own fair probability for this selection, after removing its margin.
        combined_fair *= r["implied"] / (1.0 + r["overround"])
        exp_return *= 1.0 / (1.0 + r["overround"])
    return {
        "legs": len(legs),
        "combined_odds": combined_odds,
        "combined_book_implied_prob": combined_fair,
        "book_expected_return_multiple": exp_return,
        "expected_loss_pct": 100.0 * (1.0 - exp_return),
        "one_in": (1.0 / combined_fair) if combined_fair > 0 else float("inf"),
    }


def betwinner_url(row):
    """Deep link to the fixture on Betwinner. The numeric path is used because it
    resolves without knowing the competition's URL slug."""
    sid, cid, fid = row.get("sport_id"), row.get("champ_id"), row.get("fixture_id")
    if sid and cid and fid:
        return f"https://betwinner.com/en/line/{sid}/{cid}/{fid}"
    return None


def format_summary(s):
    """Plain-text block. Says what the numbers are, and what they are not."""
    if not s:
        return "No legs to combine."
    return "\n".join([
        "=" * 68,
        f"  PARLAY of {s['legs']} legs  (Betwinner's own numbers — NOT value)",
        f"  combined decimal odds         : {s['combined_odds']:,.2f}",
        f"  combined book-implied prob    : {s['combined_book_implied_prob']:.3e}"
        f"   (~1 in {s['one_in']:,.0f})",
        f"  book expected-return multiple : {s['book_expected_return_multiple']:.4f}",
        f"  expected loss                 : {s['expected_loss_pct']:.2f}% of stake",
        "  A single book cannot yield positive expectation on its own line.",
        "  Also subject to Betwinner's per-slip payout cap and max-legs limit.",
        "=" * 68,
    ])
