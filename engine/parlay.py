"""Deep-link construction, shared by anything that needs a Betwinner fixture URL.

Historical note (docs/DECISIONS/0007): this module used to also build and summarize a
single-book parlay in the book's own implied numbers (CLAUDE.md hard rule 4), for the
now-retired scan path's opt-in `--parlay` output. That machinery — and the `overround`
field it read, which nothing in the surviving pipeline computes — was removed with it.
`betwinner_url` is unrelated to that and stays: every product this repo has ever had needs
a link to the fixture it is describing.
"""
import config
from engine import mirror


def betwinner_url(row, host=None):
    """Deep link to the fixture, on the mirror that is currently reachable.

    The host is resolved at run time (engine/mirror.py) rather than hardcoded: the book is
    blocked in Turkey and rotates its public domain, so a fixed host produces links that
    quietly stop opening. The numeric path is used because the book redirects it to its
    own slugged form, so the link resolves without us guessing a competition slug.
    """
    sid, cid, fid = row.get("sport_id"), row.get("champ_id"), row.get("fixture_id")
    if not host:
        host, _ = mirror.current(getattr(config, "REFERRAL_URL", None))
    return mirror.event_url(host, sid, cid, fid)
