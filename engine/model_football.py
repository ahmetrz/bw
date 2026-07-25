"""Football match probabilities from ClubElo's public fixture model.

    http://api.clubelo.com/Fixtures

No key, no registration. The CSV carries, per upcoming fixture, a full goal-difference
distribution (GD<-5 … GD>5) and a correct-score matrix (R:0-0 … R:6-0), which is enough
to derive 1X2 and any total-goals line.

This is the first external reference this project has had. Everything before it ranked
selections inside Betwinner's own prices and made no value claim, because with one book
there was nothing to compare against. With an independent model there is — but see the
warning in engine/edge.py before treating a computed edge as real.

ClubElo covers roughly 60 European leagues. Fixtures outside that get no probability and
are left alone rather than guessed at.
"""
import csv
import difflib
import io
import urllib.request

FIXTURES_URL = "http://api.clubelo.com/Fixtures"
UA = "bw-scanner/1.0 (odds research; contact via repo)"

# Betwinner and ClubElo spell clubs differently. Strip the noise both sides add before
# comparing, so "FC Petrocub Hincesti" and "Petrocub" can meet.
_NOISE = (
    "fc", "fk", "sk", "ac", "as", "sc", "cf", "cd", "ca", "afc", "cfr", "nk", "hnk",
    "mfk", "ofk", "rk", "us", "ud", "sv", "vfl", "vfb", "bsc", "if", "ff", "gif",
    "club", "kf", "ks", "fsv", "tsv", "psv", "sporting", "athletic", "atletico",
)


def _norm(name):
    s = (name or "").lower().replace(".", " ").replace("-", " ").replace("'", "")
    parts = [p for p in s.split() if p and p not in _NOISE]
    return " ".join(parts)


def fetch_fixtures(url=FIXTURES_URL, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return list(csv.DictReader(io.StringIO(r.read().decode("utf-8", "replace"))))


def _probs(row):
    """1X2 and total-goals probabilities from one ClubElo fixture row.

    Home win is every positive goal difference, away win every negative one. Totals come
    from the correct-score matrix rather than a Poisson fit, since the matrix is already
    the model's own joint distribution.
    """
    def f(k):
        try:
            return float(row.get(k) or 0.0)
        except ValueError:
            return 0.0

    gd_keys = [k for k in row if k.startswith("GD")]
    p_home = sum(f(k) for k in gd_keys if k in ("GD>5",) or (k.startswith("GD=") and _gd(k) > 0))
    p_away = sum(f(k) for k in gd_keys if k == "GD<-5" or (k.startswith("GD=") and _gd(k) < 0))
    p_draw = f("GD=0")

    totals = {}
    score_keys = [k for k in row if k.startswith("R:")]
    for line in (0.5, 1.5, 2.5, 3.5, 4.5, 5.5):
        over = 0.0
        for k in score_keys:
            try:
                h, a = k[2:].split("-")
                if int(h) + int(a) > line:
                    over += f(k)
            except ValueError:
                continue
        totals[line] = over

    return {
        "p_home": p_home, "p_draw": p_draw, "p_away": p_away,
        "p_over": totals,
        # The score matrix is truncated at 6-6, so it does not sum to exactly 1. Carry
        # the mass so callers can decide whether the row is complete enough to trust.
        "score_mass": sum(f(k) for k in score_keys),
    }


def _gd(key):
    try:
        return int(key.split("=", 1)[1])
    except (IndexError, ValueError):
        return 0


def build_index(rows=None):
    """(normalized home, normalized away) -> probabilities."""
    rows = fetch_fixtures() if rows is None else rows
    idx = {}
    for r in rows:
        h, a = _norm(r.get("Home")), _norm(r.get("Away"))
        if h and a:
            idx[(h, a)] = _probs(r)
            idx[(h, a)]["_names"] = (r.get("Home"), r.get("Away"))
            idx[(h, a)]["_date"] = r.get("Date")
    return idx


def lookup(index, home, away, cutoff=0.82):
    """Find a fixture, allowing for spelling differences.

    Exact match on the normalized names first; only then fuzzy, and only when BOTH
    sides clear the cutoff. A one-sided match is how you end up attaching Arsenal's
    numbers to a fixture Arsenal is not playing in.
    """
    h, a = _norm(home), _norm(away)
    if (h, a) in index:
        return index[(h, a)], 1.0
    homes = {k[0] for k in index}
    aways = {k[1] for k in index}
    hm = difflib.get_close_matches(h, homes, n=1, cutoff=cutoff)
    am = difflib.get_close_matches(a, aways, n=1, cutoff=cutoff)
    if hm and am and (hm[0], am[0]) in index:
        score = (difflib.SequenceMatcher(None, h, hm[0]).ratio()
                 + difflib.SequenceMatcher(None, a, am[0]).ratio()) / 2
        return index[(hm[0], am[0])], score
    return None, 0.0


# Betwinner market/outcome ids -> which model probability answers them.
# G=1 is 1X2 with T=1/2/3; G=17 is the match total with T=9 over / T=10 under at line P.
def model_prob(row, probs):
    """Model probability for one Betwinner selection, or None if unmapped."""
    try:
        group, line = str(row["market_key"][1]).split("|", 1)
        group = int(group)
    except (KeyError, ValueError, TypeError):
        return None
    sel = str(row.get("selection") or "")

    if group == 1:
        if sel == "1":
            return probs["p_home"]
        if sel == "X":
            return probs["p_draw"]
        if sel == "2":
            return probs["p_away"]
        return None

    if group == 17:
        try:
            ln = float(line)
        except (TypeError, ValueError):
            return None
        if ln not in probs["p_over"]:
            return None
        over = probs["p_over"][ln]
        if sel.startswith("over"):
            return over
        if sel.startswith("under"):
            return max(0.0, probs["score_mass"] - over)
        return None

    return None
