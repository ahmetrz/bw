"""Setka Cup table tennis: ratings, fixtures and — the important part — RESULTS.

    https://tabletennis.setkacup.com/api

Free, no key, and robots.txt is `Allow: /` for everyone. This matters more than it looks:
table tennis is the second-biggest sport on Betwinner's card and runs around the clock,
so when European football is out of season (as it is in late July) the daily card is
mostly this plus baseball. A model portfolio that covers only football covers nothing on
those days.

THE ENDPOINTS ARE UNDOCUMENTED and were not guessed. Blind probing found the player and
fixture routes but missed the rest; the full surface came from reading the site's own
JS bundle, which named /Players/{lang}/rating, /Players/{lang}/paged,
/Players/{id}/winners, /Players/{lang}/compare and /Matches/widget/{location}.

/Matches/widget/{locationId} is the one that changes what this project can do. It returns
completed matches with both player ids, sets won, PER-SET point scores, the winner and a
technical-result flag. That is a settled-results feed — the feedback loop the product has
been missing entirely — and it is what lets the rating scale be CALIBRATED against
outcomes rather than assumed.
"""
import json
import urllib.error
import urllib.request

BASE = "https://tabletennis.setkacup.com/api"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126 Safari/537.36")

# statusId on the widget feed, established by reading the payload rather than assuming.
# 2 is IN PROGRESS and 3 is FINISHED — the giveaway is `winner`, which is null on every
# status-2 row and carries a player object on every status-3 row. Taking 2 for "finished"
# harvests live matches at their current score, which looks like clean data and is not.
STATUS_LIVE = 2
STATUS_FINISHED = 3


def _get(path, timeout=25, tries=2):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(
                f"{BASE}{path}", headers={"Accept": "application/json", "User-Agent": UA}
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            if attempt == tries - 1:
                return None
    return None


def locations():
    """Every venue the circuit runs. Each has its own match feed."""
    return _get("/Locations/en") or []


def nearest():
    """Upcoming matches across the circuit (player ids, no odds)."""
    return _get("/Matches/nearest/en") or []


def widget(location_id=1):
    """The circuit's current scoreboard: recent matches, live and just-finished.

    The location argument is accepted by the route and then IGNORED — querying all 33
    venues returned 570 rows covering just 19 distinct matches, and 554 of those rows
    carried a locationId different from the one asked for. So this is called ONCE. The
    loop that looked thorough was fetching the same scoreboard thirty times over.

    It is also a rolling window, not an archive: roughly 19 matches at any moment. That
    is why results are accumulated by polling (tools/collect_tt.py) rather than
    downloaded in bulk — the history has to be built, it cannot be fetched.
    """
    return _get(f"/Matches/widget/{location_id}") or []


def ratings(max_pages=None):
    """Every rated player, keyed by id.

    Paged 20 at a time over ~150 pages. `ratingSc` is the circuit's own rating; some
    players also carry `ratingUttf`. Career win/loss comes along for free, which is what
    makes a sanity check on the rating possible at all.
    """
    out = {}
    first = _get("/Players/1/rating")
    if not first:
        return out
    pages = first.get("totalPages") or 1
    if max_pages:
        pages = min(pages, max_pages)

    def absorb(payload):
        for p in (payload or {}).get("players") or []:
            if p.get("id") is not None:
                out[p["id"]] = p

    absorb(first)
    for page in range(2, pages + 1):
        absorb(_get(f"/Players/1/rating?page={page}"))
    return out


def finished_matches():
    """Settled matches on the current scoreboard, normalized for grading and calibration.

    A technical result (walkover, retirement) is dropped rather than graded: it says
    nothing about who was playing better, and feeding it to a rating model teaches the
    model that the stronger player loses at random. The winner is read from the `winner`
    object rather than inferred from the set score, so a match cannot be graded before it
    has actually finished.
    """
    out = []
    for m in widget():
        if m.get("statusId") != STATUS_FINISHED:
            continue
        if m.get("technicalResult"):
            continue
        winner = m.get("winner") or {}
        if not winner.get("id"):
            continue
        p1, p2 = m.get("player1") or {}, m.get("player2") or {}
        try:
            s1, s2 = int(m.get("player1Score")), int(m.get("player2Score"))
        except (TypeError, ValueError):
            continue
        out.append({
            "match_id": m.get("id"),
            "tournament_id": m.get("tournamentId"),
            "tournament": m.get("tournamentName"),
            "location_id": m.get("locationId"),
            "start": m.get("startDate"),
            "p1_id": p1.get("id"),
            "p2_id": p2.get("id"),
            "p1_name": f"{p1.get('firstName','')} {p1.get('lastName','')}".strip(),
            "p2_name": f"{p2.get('firstName','')} {p2.get('lastName','')}".strip(),
            "sets": [s1, s2],
            "set_scores": m.get("setScores"),
            "winner_id": winner.get("id"),
            "p1_won": winner.get("id") == p1.get("id"),
        })
    return out
