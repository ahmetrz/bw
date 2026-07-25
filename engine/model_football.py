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

    # The full goal-difference distribution, keyed by margin from the home side's view.
    # This is what lets a handicap rung be priced rather than guessed: "home +1.5" wins
    # exactly when the margin is -1 or better, and the model already publishes that mass.
    # The tails are folded onto +-6 because ClubElo bins everything past 5 into GD>5 and
    # GD<-5; no handicap line we ladder to reaches that far, so the fold is harmless.
    gd = {}
    for k in gd_keys:
        if k.startswith("GD="):
            gd[_gd(k)] = gd.get(_gd(k), 0.0) + f(k)
    if f("GD>5"):
        gd[6] = gd.get(6, 0.0) + f("GD>5")
    if f("GD<-5"):
        gd[-6] = gd.get(-6, 0.0) + f("GD<-5")

    return {
        "p_home": p_home, "p_draw": p_draw, "p_away": p_away,
        "p_over": totals,
        "gd": gd,
        # The score matrix is truncated at 6-6, so it does not sum to exactly 1. Carry
        # the mass so callers can decide whether the row is complete enough to trust.
        "score_mass": sum(f(k) for k in score_keys),
    }


def handicap_probs(gd, line, side):
    """(win, push) probability for a handicap at `line` from `side`'s point of view.

    `line` is that side's own handicap: +1.5 means they may lose by one and still win the
    bet. Whole-number lines can PUSH — "+1" refunds on an exact one-goal defeat — and a
    push matters here rather than being a rounding detail: on a coupon a pushed leg is
    returned at 1.00 instead of killing the slip, so it belongs in the safety measure and
    not in the win probability.

    Quarter lines (+0.25, +0.75) are two half-stake bets a quarter either side, so they
    are priced as such: half the stake can push while the other half wins or loses.
    """
    if not gd:
        return 0.0, 0.0
    total = sum(gd.values()) or 1.0

    def one(ln):
        win = push = 0.0
        for margin, p in gd.items():
            # Margin is from the home side; flip it when pricing the away side's line.
            m = margin if side == "home" else -margin
            adj = m + ln
            if adj > 0:
                win += p
            elif adj == 0:
                push += p
        return win / total, push / total

    frac = abs(line) % 1
    if abs(frac - 0.25) < 1e-9 or abs(frac - 0.75) < 1e-9:
        w1, p1 = one(line - 0.25)
        w2, p2 = one(line + 0.25)
        return (w1 + w2) / 2.0, (p1 + p2) / 2.0
    return one(line)


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


def rung_probs(row, probs):
    """(win, push) probability for one selection, or None where the model cannot reach it.

    Covers every market the safety ladder can select: the 1X2, double chance, both
    handicap families and the match total. Push is reported separately because a pushed
    leg is refunded rather than lost, which is the difference between a coupon surviving
    and dying, and no other market in the ladder has that property.
    """
    try:
        group = int(str(row["market_key"][1]).split("|", 1)[0])
        line_txt = str(row["market_key"][1]).split("|", 1)[1]
    except (KeyError, ValueError, TypeError, IndexError):
        return None
    oid = row.get("outcome_id")
    gd = probs.get("gd") or {}

    if group == 1:
        return ({1: (probs["p_home"], 0.0),
                 2: (probs["p_draw"], 0.0),
                 3: (probs["p_away"], 0.0)}).get(oid)

    if group == 8:   # double chance
        return ({4: (probs["p_home"] + probs["p_draw"], 0.0),
                 5: (probs["p_home"] + probs["p_away"], 0.0),
                 6: (probs["p_draw"] + probs["p_away"], 0.0)}).get(oid)

    if group in (2, 2854):
        side = "home" if oid in (7, 3829) else ("away" if oid in (8, 3830) else None)
        if side is None:
            return None
        try:
            stored = float(line_txt)
        except (TypeError, ValueError):
            return None
        # market_key holds the line as the HOME side sees it; the away side's own
        # handicap is its negation.
        own = stored if side == "home" else -stored
        return handicap_probs(gd, own, side)

    if group == 17:
        try:
            ln = float(line_txt)
        except (TypeError, ValueError):
            return None
        if ln not in probs["p_over"]:
            return None
        over = probs["p_over"][ln]
        if oid == 9:
            return (over, 0.0)
        if oid == 10:
            return (max(0.0, probs["score_mass"] - over), 0.0)
        return None

    return None


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
