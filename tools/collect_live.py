#!/usr/bin/env python3
"""Collect finished results from the book's OWN live feed, for every sport it runs.

    python tools/collect_live.py                      # one sweep
    python tools/collect_live.py --minutes 350        # keep sweeping for ~6 hours
    python tools/collect_live.py --sports 10,6 --dry-run

WHY THIS EXISTS. Every result source before this one was somebody else's: football-data
for football, EuroLeague for basketball, MLB for baseball, Setka for table tennis. Each
had to be found, checked against robots.txt by our crawler's name, qualified on its body,
and each covered exactly one slice. Setka's archive is Setka Cup and nothing else, so 58%
of the table tennis card — Pro League, TT-Cup, Masters — had no source at all, and
volleyball, snooker, darts, futsal and handball had none either. Several of the obvious
candidates are disallowed to us by name and that will not change.

The book is running all of those matches itself and publishing the score while they are
played. `LiveFeed/Get1x2_VZip` returns, per live fixture: both names, both STABLE
participant ids, the competition, the running score in `SC.FS`, the period breakdown in
`SC.PS`, the current period in `SC.CPS`, and the format in `MIS` K=3. It is the same
service-api this project already fetches its card from.

So results are no longer looked for. They are WATCHED. One collector, every sport, every
circuit the book carries — including the ones no free archive covers.

TWO WAYS A MATCH GETS WRITTEN DOWN, and the first is far better than the second:

  1. The feed SAYS SO. `SC.CPS` becomes "Match finished" and the fixture lingers for a
     while before it is dropped. Nothing is inferred; the book states the match is over
     and states the score. Sweeping often enough to catch that window is the whole job.
  2. It VANISHED. If a fixture is gone and its last seen score looks finished for its
     format, it is recorded. This is the fallback, and it is the one that can be wrong,
     so it is fenced (see `looks_finished`).

WHAT IT REFUSES TO RECORD, because a watcher that guesses is worse than no watcher:
  * a sport whose finish condition we cannot state — it is simply not in `SPORTS` below.
    "Probably over by now" is not a result.
  * a fixture that vanished before it started: that is a cancellation.
  * a fixture whose last score does not look finished for ITS OWN format, which catches
    an abandonment and a mid-match feed drop with the same rule. The format is READ off
    the book's note, not assumed: the same table tennis circuit runs best-of-five and
    best-of-seven on the same day, and a 3-1 win looks unfinished if you assume seven.
  * a fixture last seen too recently to be sure it is gone rather than momentarily absent.
  * a tie in a sport that cannot end tied.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import results_store  # noqa: E402

BASE = "https://betwinner.com/service-api/LiveFeed"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126 Safari/537.36")
STATE = "data/live_state.json"

# THE WATCH LIST, and it is deliberately a list of finish CONDITIONS rather than of sports.
# A sport is here only when we can say what a completed match of it looks like; everything
# else — motorsport, golf, the marble leagues, the card games, the simulated FIFA ladders —
# is absent because that sentence cannot be written for it honestly.
#
#   unit    what the score counts, which decides the markets the model may price
#           (engine/model_generic.HANDICAP_GROUPS keys off exactly this word)
#   kind    "target"  a race to N sets/frames/maps/legs; the winner must REACH N
#           "periods" a fixed number of scheduled periods; the last one must be reached
#   n       the default for that rule, or None where the sport runs SEVERAL formats on the
#           same card and the note must be read instead. Tennis (Bo3 and Bo5) and table
#           tennis (Bo5 and Bo7) are the two that must be read.
SPORTS = {
    1:   ("goals",  "periods", 2),      # football — two halves
    2:   ("goals",  "periods", 3),      # ice hockey — three periods
    3:   ("points", "periods", 4),      # basketball — four quarters
    4:   ("sets",   "target",  None),   # tennis — Bo3 and Bo5 share a card
    5:   ("runs",   "periods", 9),      # baseball — nine innings
    6:   ("sets",   "target",  3),      # volleyball, indoor — best of five
    8:   ("goals",  "periods", 2),      # handball — two halves
    10:  ("sets",   "target",  None),   # table tennis — Bo5 and Bo7 share a card
    14:  ("goals",  "periods", 2),      # futsal — two halves
    16:  ("sets",   "target",  2),      # badminton — best of three
    17:  ("goals",  "periods", 4),      # water polo — four quarters
    21:  ("sets",   "target",  None),   # darts — legs or sets, always noted
    27:  ("goals",  "periods", 4),      # field hockey — four quarters
    29:  ("sets",   "target",  2),      # beach volleyball — best of three
    30:  ("frames", "target",  None),   # snooker — frame count is always noted
    40:  ("maps",   "target",  None),   # esports — best of N maps, always noted
    49:  ("points", "periods", 4),      # netball — four quarters
    83:  ("runs",   "periods", 7),      # softball — seven innings
    86:  ("maps",   "target",  None),   # counter strike
    97:  ("maps",   "target",  None),   # dota
    109: ("maps",   "target",  None),   # rocket league
    125: ("maps",   "target",  None),   # call of duty
    150: ("maps",   "target",  None),   # starcraft 2
    298: ("maps",   "target",  None),   # overwatch
    180: ("points", "periods", 2),      # kabaddi — two halves
}

# Sports that can legitimately finish level. Everywhere else a tie in the last seen score
# means we caught the match mid-flight, not that it ended that way.
CAN_DRAW = {1, 8, 14, 27, 17, 66}

# What the feed says when a match is over. Checked case-folded and as a substring, because
# the wording varies by sport ("Match finished", "Ended").
FINISHED = ("finish", "ended", "full time", "match over")

# A fixture unseen for less than this may just have been missed by one sweep. Kept short
# because the whole vanish path has to complete INSIDE a run: a twenty-minute wait inside
# a ten-minute job never fires. It can be short safely because a failed request no longer
# looks like a vanished fixture — a sport whose fetch came back empty is skipped entirely
# rather than having all of its matches declared over at once.
GONE_AFTER = 3 * 60

# And one unseen for longer than this is stale state rather than a result we can trust.
# A day, so that fixtures still in flight when a run ends are settled by the next one:
# `looks_finished` is what protects correctness here, and it does not get weaker with age.
FORGET_AFTER = 24 * 3600

# A sport that came back empty this many sweeps running is checked only occasionally after
# that. Volleyball is dead at 04:00 UTC and the sweep should not pay for it every two
# minutes; it is re-checked often enough to notice when a card starts.
QUIET_AFTER = 3
RECHECK_EVERY = 10


def _get(url, timeout=30, tries=3):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = json.loads(r.read().decode("utf-8", "replace"))
            return body.get("Value") or []
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            if attempt + 1 < tries:
                time.sleep(1.5 * (attempt + 1))
    return []


def fetch(sport):
    return _get(f"{BASE}/Get1x2_VZip?sports={sport}&count=200&lng=en&mode=4"
                f"&partner=159&getEmpty=true")


# "7 Games Match (4 Games up to win)" — the explicit form, and the one to trust.
_UP_TO_WIN = re.compile(r"(\d+)\s+\w+\s+up\s+to\s+win", re.I)
# "7 Games Match", "35 Legs Matches", "5 Sets Match"
_BEST_OF_N = re.compile(r"^(\d+)\s+(games?|sets?|frames?|legs?|maps?|rounds?)\b", re.I)
# "Best of 3 maps"
_BEST_OF = re.compile(r"best\s+of\s+(\d+)", re.I)
# "4x10", "3x5" — periods by duration, the note basketball and ice hockey carry
_PERIODS = re.compile(r"^(\d+)\s*[x×]\s*\d+", re.I)


def format_of(game, sport):
    """(kind, n) — what finishing this particular fixture requires.

    Read off the book's own format note where there is one, because the alternative is
    assuming, and assuming is how a 3-1 lead in a best-of-seven gets written down as a win.
    Falls back to the sport's default ONLY where that sport runs a single format; where it
    runs several, the default is None and an unreadable note means the fixture is refused.
    """
    unit, kind, default = SPORTS[sport]
    note = ""
    for item in game.get("MIS") or []:
        if item.get("K") == 3:
            note = str(item.get("V") or "")
            break

    if note:
        m = _UP_TO_WIN.search(note)
        if m:
            return "target", int(m.group(1))
        m = _BEST_OF_N.match(note.strip()) or _BEST_OF.search(note)
        if m:
            best_of = int(m.group(1))
            if 1 <= best_of <= 51:
                return "target", best_of // 2 + 1
        m = _PERIODS.match(note.strip())
        if m and 1 <= int(m.group(1)) <= 9:
            return "periods", int(m.group(1))

    return (kind, default) if default else (kind, None)


def snapshot(game, sport):
    """What we need to remember about one live fixture, or None if it is not one."""
    gid, o1, o2 = game.get("I"), game.get("O1"), game.get("O2")
    if not gid or not o1 or not o2:
        return None
    sc = game.get("SC") or {}
    fs = sc.get("FS") or {}
    if "S1" not in fs and "S2" not in fs:
        return None                       # not under way; nothing to remember yet
    kind, n = format_of(game, sport)
    return {
        "sport": sport,
        "league": game.get("L"),
        "p1": o1, "p2": o2,
        "id1": str(game.get("O1I") or ""), "id2": str(game.get("O2I") or ""),
        "s1": int(fs.get("S1") or 0), "s2": int(fs.get("S2") or 0),
        "start": int(game.get("S") or 0),
        "kind": kind, "n": n,
        # How far the match has got. `CP` is the current period; `PS` is the list of
        # periods that have a score, and one of the two is present for every sport.
        "period": int(sc.get("CP") or len(sc.get("PS") or []) or 0),
        "cps": (sc.get("CPS") or "").strip(),
        "seen": int(time.time()),
    }


def is_finished_now(rec):
    """Did the feed itself say the match is over? The clean path, with nothing inferred."""
    low = rec.get("cps", "").lower()
    return any(word in low for word in FINISHED)


def placeable(rec):
    """Can we say which RATING SCALE this result belongs on?

    A race to four sets and a race to three are different bets, so they are different
    pools, and a row we cannot place lands in a nameless one where a player's history is
    split from itself. So an unreadable format refuses the row on BOTH paths — even the
    one where the feed stated the match was over. Knowing the score is not enough; we also
    have to know what it was a race to.
    """
    return rec["kind"] != "target" or bool(rec.get("n"))


def settle_target(rec):
    """Fill in a race's target from a FINISHED score, where doing so is definitional.

    Only ever called once the feed has stated the match is over, and only then is this
    sound: a race ends the moment somebody reaches the target, so in a completed match the
    winner's tally IS the target. Nothing is being inferred from a partial score — that is
    exactly what `looks_finished` refuses to do. It recovers the fixtures whose format note
    the book simply omits, which on a live card was every CTT World Championship match: a
    real 0-4 was thrown away for want of a line saying "7 Games Match".
    """
    if rec["kind"] != "target" or rec.get("n"):
        return rec
    reached = max(rec["s1"], rec["s2"])
    if 1 <= reached <= 15:
        rec = dict(rec, n=reached)
    return rec


def looks_finished(rec):
    """Does this last-seen score look like a completed match for its own format?

    The guard that separates a result from an abandonment, and the only place this
    collector reasons rather than reads. Deliberately strict: every branch that cannot
    answer returns False, so an unknown format costs us a result rather than inventing one.

    IT ONLY ANSWERS FOR A RACE, and that limit is the point. In a set, frame, map or leg
    sport the score ITSELF says the match is over: nobody reaches four in a best-of-seven
    and plays on. A period sport has no such tell. A football match seen at 1-0 in the
    second half and gone by the next sweep satisfies every structural check — right
    period, plausible score — and may well have finished 3-1, so recording it writes down
    a scoreline that never happened. Being in the last period is not being finished, and
    there is no reading of the payload that turns one into the other. Period sports are
    therefore recorded ONLY when the feed itself says "Match finished" (`is_finished_now`),
    which costs some football results and no correctness. That is the right way round:
    football, basketball, baseball and hockey all have archives behind them, and the
    sports this watcher EXISTS for — table tennis, volleyball, snooker, darts, badminton,
    esports — are races, every one of them.
    """
    s1, s2 = rec["s1"], rec["s2"]
    n = rec.get("n")
    if rec["kind"] != "target":
        return False
    if not n:
        return False                       # format unreadable — refuse, do not guess
    if s1 == s2 and rec["sport"] not in CAN_DRAW:
        return False                       # caught mid-flight, not a drawn result
    # A race: somebody has to have got there, and the loser must NOT have got there too,
    # which would mean we are reading a running total rather than a final one.
    return max(s1, s2) >= n and min(s1, s2) < n


def to_result(rec, now):
    unit = SPORTS[rec["sport"]][0]
    row = {
        "date": time.strftime("%Y-%m-%d", time.gmtime(rec.get("start") or now)),
        "home": rec["p1"], "away": rec["p2"],
        "home_score": rec["s1"], "away_score": rec["s2"],
        "league": rec.get("league"), "unit": unit,
        "source": "betwinner-live",
    }
    # Stable identity beats a name every time: a player is renamed, transliterated and
    # sponsor-suffixed, and the id survives all three.
    if rec.get("id1") and rec.get("id2"):
        row["home_id"], row["away_id"] = rec["id1"], rec["id2"]
    # A race to four sets is a different bet from a race to three, so it is a different
    # rating scale. Same reason tennis is split into bo3 and bo5.
    if rec["kind"] == "target" and rec.get("n"):
        row["pool"] = f"bo{rec['n'] * 2 - 1}"
    return row


def read_state(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def write_state(path, state):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, path)


def sweep(state, ids, quiet, round_no):
    """One pass over the live feed. Returns (finished rows by sport, counters)."""
    now = int(time.time())
    seen_ids, answered, live, done = set(), set(), 0, {}

    for sport in ids:
        if quiet.get(sport, 0) >= QUIET_AFTER and round_no % RECHECK_EVERY:
            continue
        games = fetch(sport)
        quiet[sport] = 0 if games else quiet.get(sport, 0) + 1
        if not games:
            # Empty is ambiguous — no card, or three failed requests. Either way this
            # sport's fixtures are NOT treated as vanished this round, which is what lets
            # the vanish threshold be minutes instead of tens of minutes.
            continue
        answered.add(sport)
        for game in games:
            rec = snapshot(game, sport)
            if not rec:
                continue
            gid = str(game["I"])
            seen_ids.add(gid)
            live += 1
            if is_finished_now(rec):
                # The book says it is over. Take it and stop watching.
                rec = settle_target(rec)
                if placeable(rec):
                    done.setdefault(sport, []).append(to_result(rec, now))
                state.pop(gid, None)
                continue
            state[gid] = rec
        time.sleep(0.2)

    dropped, waiting = 0, 0
    for gid, rec in list(state.items()):
        if gid in seen_ids or rec["sport"] not in answered:
            continue
        age = now - int(rec.get("seen") or 0)
        if age < GONE_AFTER:
            waiting += 1
            continue
        state.pop(gid, None)
        if age > FORGET_AFTER or not looks_finished(rec):
            dropped += 1
            continue
        done.setdefault(rec["sport"], []).append(to_result(rec, now))

    return done, {"live": live, "waiting": waiting, "dropped": dropped}


def store(done, dry_run):
    total = 0
    for sport, rows in sorted(done.items()):
        if dry_run:
            print(f"    would store {len(rows):>3} for sport {sport}")
            continue
        added, held = results_store.merge(sport, rows)
        total += added
        print(f"    sport {sport:<4} +{added:>3} new ({len(rows)} finished) · {held} stored")
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default=STATE)
    ap.add_argument("--sports", default="", help="csv of sport ids; blank = the watch list")
    ap.add_argument("--minutes", type=float, default=0,
                    help="keep sweeping for this long; 0 = one sweep and exit")
    ap.add_argument("--every", type=int, default=150, help="seconds between sweeps")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    ids = [int(x) for x in args.sports.split(",") if x.strip()] or sorted(SPORTS)
    unknown = [i for i in ids if i not in SPORTS]
    if unknown:
        print(f"no finish condition defined for sport(s) {unknown} — "
              f"add one to SPORTS or leave them unwatched", file=sys.stderr)
        return 1

    state = read_state(args.state)
    quiet, round_no, added, deadline = {}, 0, 0, time.time() + args.minutes * 60
    while True:
        round_no += 1
        done, counts = sweep(state, ids, quiet, round_no)
        finished = sum(len(v) for v in done.values())
        print(f"[{time.strftime('%H:%M:%S')}] sweep {round_no}: {counts['live']} live · "
              f"{finished} finished · {counts['waiting']} waiting · "
              f"{counts['dropped']} refused · {len(state)} watched")
        if done:
            added += store(done, args.dry_run)
        if not args.dry_run:
            write_state(args.state, state)
        if time.time() + args.every > deadline:
            break
        time.sleep(args.every)

    print(f"recorded {added} new results over {round_no} sweep(s) · "
          f"{len(state)} fixtures still being watched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
