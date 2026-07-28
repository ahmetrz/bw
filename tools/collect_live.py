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
  2. It VANISHED, and the state it was last seen in says the match was over — the score
     for a race, the CLOCK for a period sport. This is the fallback, and it is the one
     that can be wrong, so it is fenced (see `looks_finished`).

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

from engine import results_store, simulated  # noqa: E402

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
#           "periods" a fixed number of scheduled periods
#   n       the default for that rule, or None where the sport runs SEVERAL formats on the
#           same card and the note must be read instead. Tennis (Bo3 and Bo5) and table
#           tennis (Bo5 and Bo7) are the two that must be read.
#
# For a PERIOD sport `n` documents the format and nothing more: `looks_finished` refuses
# that whole class, so those sports are recorded only when the feed states the match is
# over. The number is kept because it is the sentence that admitted the sport, and the
# next person to touch the vanish path needs to see it.
SPORTS = {
    1:   ("goals",  "periods", 2),      # football — two halves
    2:   ("goals",  "periods", 3),      # ice hockey — three periods
    3:   ("points", "periods", 4),      # basketball — four quarters
    4:   ("sets",   "target",  None),   # tennis — Bo3 and Bo5 share a card
    5:   ("runs",   "periods", 9),      # baseball — nine innings
    6:   ("sets",   "target",  3),      # volleyball, indoor — best of five
    8:   ("goals",  "periods", 2),      # handball — two halves
    10:  ("sets",   "target",  None),   # table tennis — Bo5 and Bo7 share a card
    12:  ("frames", "target",  None),   # billiards — pyramid, a race to frames
    13:  ("points", "periods", 4),      # american football — four quarters
    14:  ("goals",  "periods", 2),      # futsal — two halves
    16:  ("sets",   "target",  2),      # badminton — best of three
    17:  ("goals",  "periods", 4),      # water polo — four quarters
    21:  ("sets",   "target",  None),   # darts — legs or sets, always noted
    27:  ("goals",  "periods", 4),      # field hockey — four quarters
    29:  ("sets",   "target",  2),      # beach volleyball — best of three
    30:  ("frames", "target",  None),   # snooker — frame count is always noted
    40:  ("maps",   "target",  None),   # esports — best of N maps, always noted
    48:  ("points", "periods", 4),      # lacrosse — four quarters
    49:  ("points", "periods", 4),      # netball — four quarters
    60:  ("points", "target",  None),   # fencing — a bout is a race to 15 hits
    66:  ("runs",   "periods", 2),      # cricket — two innings a side in a limited match
    83:  ("runs",   "periods", 7),      # softball — seven innings
    86:  ("maps",   "target",  None),   # counter strike
    97:  ("maps",   "target",  None),   # dota
    109: ("maps",   "target",  None),   # rocket league
    125: ("maps",   "target",  None),   # call of duty
    150: ("maps",   "target",  None),   # starcraft 2
    282: ("sets",   "target",  None),   # padel — "5 Sets Match to 11 points", so it is read
    283: ("sets",   "target",  None),   # pickleball
    298: ("maps",   "target",  None),   # overwatch
    180: ("points", "periods", 2),      # kabaddi — two halves
}

# NOT watched, and each for a reason rather than an omission. Data rather than a comment,
# because tools/make_method_page.py reports it: "no source yet" and "cannot have a source"
# are different answers and the operator should not have to guess which one applies.
UNWATCHABLE = {
    9:   "kazanan hakem kararı veya nakavtla belirlenir — skor ÇİFTİ yok, dolayısıyla "
         "fark yok; genel model fark dağılımı kuruyor",
    189: "kazanan hakem kararı veya nakavtla belirlenir — skor çifti yok",
    307: "gösteri güreşi — sonucu önceden belirlenmiş",
    11:  "1 / 0.5 / 0 puanlanır ve günlerce sürer — fark dağılımı yok",
    18:  "yarış, ikili karşılaşma değil — sert kural 7",
    37:  "yarış, ikili karşılaşma değil — sert kural 7",
    41:  "sahada herkes birbirine karşı — ikili karşılaşma değil",
    44:  "yarış, ikili karşılaşma değil — sert kural 7",
    57:  "yarış, ikili karşılaşma değil — sert kural 7",
    68:  "yarış, ikili karşılaşma değil — sert kural 7",
    92:  "yarış, ikili karşılaşma değil — sert kural 7",
    102: "yarış, ikili karşılaşma değil — sert kural 7",
    220: "yarış, ikili karşılaşma değil — sert kural 7",
    85:  "simülasyon: bir video oyunu, gerçek bir karşılaşma değil — sert kural 9",
    144: "simülasyon: bir video oyunu, gerçek bir karşılaşma değil — sert kural 9",
    103: "simülasyon — sert kural 9",
    321: "simülasyon — sert kural 9",
}

# Sports that can legitimately finish level. Everywhere else a tie in the last seen score
# means we caught the match mid-flight, not that it ended that way.
CAN_DRAW = {1, 8, 13, 14, 17, 27, 66}

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


# THE SHORTEST PERIOD A REAL MATCH OF THIS SPORT IS PLAYED OVER, in minutes. Only checked
# when the book DECLARES a period length, which it does for anything non-standard.
#
# Sport 1 is not one game. On a live card it carries "Short Football 3x3" at two halves of
# five minutes, "Subsoccer" at 2x5, "MLS+" at 2x10, "Student League" at 2x15 — alongside
# China Foshan La Liga at 2x40 and ordinary football, which declares nothing at all. They
# are all filed as football and they do not produce the same scorelines: a five-minute half
# and a forty-five-minute half are different games with different goal distributions.
#
# Storing them together would corrupt the very thing the model reads. 138,835 results of
# ninety-minute football teach nothing about a ten-minute one, and the model cannot tell
# from a stored row which it was looking at.
MIN_PERIOD_MINUTES = {
    1: 30,     # football — real halves are 40 or 45; everything short-sided is well below
    2: 10,     # ice hockey — 15 or 20
    3: 8,      # basketball — 10 or 12
    8: 20,     # handball — 30
    14: 15,    # futsal — 20
    17: 5,     # water polo — 8
}

# "2 halves of 20 minutes" and "2x10" — the two ways a period length is declared.
_PERIOD_MINUTES = re.compile(r'^(\d+)\s*(?:[x×]\s*(\d+)|\s*halves?\s+of\s+(\d+))', re.I)


def period_shape(note):
    """(periods, minutes each) as DECLARED by the note, or (None, None)."""
    m = _PERIOD_MINUTES.match((note or "").strip())
    if not m:
        return None, None
    mins = m.group(2) or m.group(3)
    try:
        return int(m.group(1)), int(mins)
    except (TypeError, ValueError):
        return None, None


def period_minutes(note):
    """Declared minutes per period, or None when the note does not state one."""
    return period_shape(note)[1]


def real_format(sport, note):
    """False when the book declares a period far shorter than the sport is really played.

    A declared length is the book telling us this is a different product. Absent, we
    assume the standard game, which is what ordinary football does — it declares nothing.
    """
    need = MIN_PERIOD_MINUTES.get(sport)
    if not need:
        return True
    got = period_minutes(note)
    return got is None or got >= need


# SPORTS WHOSE CLOCK WE HAVE READ, and the length of regulation time in seconds.
#
# A period sport has no score that says "over" — 1-0 in the second half looks exactly like
# 1-0 at full time — which is why the vanish path refused the whole class. But the feed
# publishes a CLOCK, and an end-of-match probe on real football showed the clock says it
# plainly: `SC.TS` counts up to 5400 and stops there, and `SC.SLS` — the human string,
# "84 minutes" — goes EMPTY at the same moment. Three matches watched to their end, three
# times that pair; the one still being played at the time sat at TS=5034 / SLS="84
# minutes". Only one of the three ever showed "Match finished", so the other two were
# results this collector was throwing away.
#
# This table is short on purpose. It is a list of sports whose TS/SLS semantics were
# WATCHED, not a list of sports that have a clock. Basketball and hockey have one too and
# are absent, because nobody has yet seen one of their matches end here — a game clock
# that counts DOWN, or a period clock that resets, would satisfy this rule at half time.
# To add a sport: probe it to its end, confirm the pair, then add the line.
CLOCK_FINISH = {
    1: 90 * 60,     # football — two forty-five minute halves
}

# The clock reaching regulation is not the end of the match if there is more scheduled
# after it, and extra time changes the score AFTER the result our markets settle on. Both
# are refused: the period must be the last one, and the status must not name an overtime.
EXTRA = ("extra", "overtime", "penalt", "shoot")


def regulation_seconds(rec):
    """Length of this fixture's regulation time, or None if the sport's clock is unread.

    Read off the note where the book declares one — "2x40" is an eighty-minute game and
    its clock stops eighty minutes in — and only otherwise from the sport's default.
    """
    default = CLOCK_FINISH.get(rec["sport"])
    if default is None:
        return None
    periods, minutes = period_shape(rec.get("note"))
    if periods and minutes:
        return periods * minutes * 60
    return default


def clock_says_over(rec):
    """Has this fixture's clock run out, with nothing scheduled after it?

    Four conditions, and every one of them has to hold:
      * the sport's clock has been watched to the end of a match (`CLOCK_FINISH`);
      * `SLS` is EMPTY — while a match is being played the feed reports the minute, so a
        running clock is a match still running;
      * `TS` has reached regulation;
      * we are in the last scheduled period and the status names no overtime, because a
        match going to extra time keeps playing and its final score is not the one the
        markets we price settle on.
    """
    full = regulation_seconds(rec)
    if full is None or rec.get("sls"):
        return False
    if int(rec.get("ts") or 0) < full:
        return False
    if any(word in (rec.get("cps") or "").lower() for word in EXTRA):
        return False
    return bool(rec.get("n")) and rec.get("period") == rec["n"]


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
    note = note_of(game)

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


# Sports where the FORMAT NOTE itself is the rating scale, because the same two sides
# playing a different format produce a different distribution entirely. A Test innings
# runs to three hundred and a T20 innings to a hundred and eighty; pooled, the model would
# price a T20 run handicap off scores no T20 can reach. Race sports get this for free —
# their pool comes from the target — so this is only for the period sports that need it.
POOL_BY_FORMAT = {66}


def note_of(game):
    """The book's format note for this fixture, e.g. "T20", "7 Games Match", "4x10"."""
    for item in game.get("MIS") or []:
        if item.get("K") == 3:
            return str(item.get("V") or "").strip()
    return ""


def snapshot(game, sport):
    """What we need to remember about one live fixture, or None if it is not one."""
    gid, o1, o2 = game.get("I"), game.get("O1"), game.get("O2")
    if not gid or not o1 or not o2:
        return None
    sc = game.get("SC") or {}
    fs = sc.get("FS") or {}
    ts = int(sc.get("TS") or 0)
    # `FS` omits a zero, so a goalless match has no score at all and used to look like one
    # that had not begun. A running CLOCK says otherwise, and dropping those would drop
    # every 0-0 — which is not a rare scoreline but roughly one football match in twelve,
    # and losing it systematically would tilt the model's goal distribution upward.
    if "S1" not in fs and "S2" not in fs and ts <= 0:
        return None                       # not under way; nothing to remember yet
    kind, n = format_of(game, sport)
    return {
        "sport": sport,
        "league": game.get("L"),
        "p1": o1, "p2": o2,
        "id1": str(game.get("O1I") or ""), "id2": str(game.get("O2I") or ""),
        "s1": int(fs.get("S1") or 0), "s2": int(fs.get("S2") or 0),
        "start": int(game.get("S") or 0),
        "kind": kind, "n": n, "note": note_of(game),
        # How far the match has got. `CP` is the current period; `PS` is the list of
        # periods that have a score, and one of the two is present for every sport.
        "period": int(sc.get("CP") or len(sc.get("PS") or []) or 0),
        "cps": (sc.get("CPS") or "").strip(),
        # The clock, both ways the feed states it: `TS` in seconds and `SLS` as the minute
        # in words. They disagree in exactly one situation and that situation is the end of
        # the match — see `clock_says_over`.
        "ts": ts,
        "sls": (sc.get("SLS") or "").strip(),
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
    # A game the book declares as much shorter than the real sport is a DIFFERENT product
    # filed under the same id — five-minute halves do not produce ninety-minute
    # scorelines, and nothing in a stored row would say which it had been.
    if not real_format(rec["sport"], rec.get("note")):
        return False
    if rec["kind"] != "target":
        # A period sport is placed by its format note where the format changes the
        # distribution, and by nothing where it does not.
        return rec["sport"] not in POOL_BY_FORMAT or bool(rec.get("note"))
    return bool(rec.get("n"))


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


# TENNIS DOES NOT DECLARE ITS FORMAT, AND WITHOUT ONE NOTHING IS EVER COLLECTED.
#
# Every other race sport states the target somewhere — "7 Games Match", "Best of 3 maps",
# "5 Sets Match to 11 points". Tennis states nothing: on a live card of 74 fixtures the
# format note was empty on 61 and read "3rd set champ tiebreak" on the other 13, and the
# whole `MIS` block is venue, surface, round, seeding and weather. So `format_of` returns
# no target, `placeable` refuses the row, and the sport is uncollectable except in the
# narrow case where the feed itself announces the finish and `settle_target` reads the
# target off the completed score. Ten rows in four days, against 29,774 from the archive
# — and the archive is six months stale (TML's 2026 file ends on 17 January), so tennis
# has no working source at all.
#
# What can be said truthfully: best-of-five is Grand Slam men's singles and nothing else.
# Every ATP 250/500/1000, every WTA event at every level, every Challenger and every ITF
# is best of three — TML's entire 2026 file is best_of=3 for all 137 matches. That is the
# sport's rulebook, and it is the same kind of fact as "football has two halves", which
# this file already encodes for twenty other sports.
#
# Two guards, because a name list is a weaker thing than a read:
#   * a Grand Slam by name is REFUSED on this path rather than assumed to be five, since
#     2-0 there is a lead and not a result. The feed-says-finished path still takes them.
#   * ANY score reaching three sets cannot be a best-of-three, whatever the competition is
#     called, so the score itself overrides the default. A Grand Slam we failed to
#     recognise is caught by arithmetic instead of by spelling.
BEST_OF_FIVE = ("australian open", "roland garros", "french open", "wimbledon",
                "us open", "davis cup")
SPORT_TENNIS = 4


def with_target(rec):
    """Fill in tennis's unstated target. Everything else keeps whatever it declared.

    Sits on the VANISH path, where `settle_target` cannot help: that one reads the target
    off a score the feed has confirmed is final, and here nothing has confirmed anything.
    """
    if rec["sport"] != SPORT_TENNIS or rec["kind"] != "target" or rec.get("n"):
        return rec
    # No best-of-three reaches three sets, so a score that does settles its own format,
    # whatever the competition is called. Checked FIRST, so it applies to the Grand Slams
    # too — 3-1 at Wimbledon is a finished match and there is nothing to guess about it.
    if max(rec["s1"], rec["s2"]) >= 3:
        return dict(rec, n=3)
    if any(name in (rec.get("league") or "").lower() for name in BEST_OF_FIVE):
        return rec                         # 2-0 there is a lead; refuse rather than guess
    return dict(rec, n=2)


def looks_finished(rec):
    """Does this last-seen score look like a completed match for its own format?

    The guard that separates a result from an abandonment, and the only place this
    collector reasons rather than reads. Deliberately strict: every branch that cannot
    answer returns False, so an unknown format costs us a result rather than inventing one.

    TWO THINGS CAN SAY SO, and neither of them is the score being plausible.

    In a set, frame, map or leg sport the score ITSELF says the match is over: nobody
    reaches four in a best-of-seven and plays on. That is the race branch below.

    A period sport has no such tell — 1-0 in the second half looks exactly like 1-0 at full
    time, and a match seen at 1-0 and gone by the next sweep may well have finished 3-1, so
    recording the structural check alone writes down a scoreline that never happened. That
    is why this whole class was refused. What replaces the refusal is not a better guess
    about the score but a DIFFERENT FIELD: the clock, which the feed publishes and which
    stops. `clock_says_over` is that reading, and it is enabled only for the sports whose
    clock has been watched to the end of a real match.

    The residual exposure is stated rather than hidden: a fixture that both reaches
    regulation and disappears for three minutes while injury time is still being played
    would be recorded at its 90-minute score. It is a narrow window and the alternative
    costs most of the sport, since only one football match in three announces itself as
    finished before it drops off the feed.
    """
    s1, s2 = rec["s1"], rec["s2"]
    n = rec.get("n")
    if s1 == s2 and rec["sport"] not in CAN_DRAW:
        return False                       # caught mid-flight, not a drawn result
    if rec["kind"] != "target":
        # A period sport: the clock, or nothing.
        return clock_says_over(rec)
    if not n:
        return False                       # format unreadable — refuse, do not guess
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
    elif rec["sport"] in POOL_BY_FORMAT and rec.get("note"):
        row["pool"] = rec["note"][:32]
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


def sweep(state, ids, quiet, round_no, fake=None):
    """One pass over the live feed. Returns (finished rows by sport, counters)."""
    now = int(time.time())
    seen_ids, answered, live, done = set(), set(), 0, {}
    fake = fake or {}

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
            # A competition whose schedule is physically impossible is generated, and its
            # "results" would teach the model about teams that never played. Flagged by
            # the daily run, which sees a whole card; refused here.
            if (sport, rec.get("league")) in fake:
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
        rec = with_target(rec)
        # `placeable` matters on this path now. It used to be implied — the only fixtures
        # `looks_finished` accepted were races with a readable target, which is what
        # `placeable` asks of them — but a period sport reaching the clock rule does not
        # answer it, and a five-minute-half game filed under football would otherwise be
        # stored beside the ninety-minute ones.
        if age > FORGET_AFTER or not (placeable(rec) and looks_finished(rec)):
            dropped += 1
            continue
        done.setdefault(rec["sport"], []).append(to_result(rec, now))

    return done, {"live": live, "waiting": waiting, "dropped": dropped}


# A running ledger of what was collected and WHEN. One line per sport per sweep, so a few
# a minute at most. It exists because the daily coverage report answers the operator's
# standing question — when will the other sports be modelled — and that answer is a RATE,
# which cannot be recovered afterwards: the store keeps each fixture's own date, not the
# moment we learned about it, so a watcher that has run for three hours looks identical to
# one that has run for a day.
LEDGER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "watch_log.jsonl")


def note(added, path=LEDGER):
    if not added:
        return
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a") as f:
            for sport, n in sorted(added.items()):
                f.write(json.dumps({"at": stamp, "sport": sport, "added": n}) + "\n")
    except OSError:
        pass                              # a missing ledger costs a projection, not a result


def store(done, dry_run):
    total, added_by_sport = 0, {}
    for sport, rows in sorted(done.items()):
        if dry_run:
            print(f"    would store {len(rows):>3} for sport {sport}")
            continue
        added, held = results_store.merge(sport, rows)
        total += added
        if added:
            added_by_sport[sport] = added
        print(f"    sport {sport:<4} +{added:>3} new ({len(rows)} finished) · {held} stored")
    note(added_by_sport)
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
    fake = simulated.load()
    if fake:
        print(f"refusing {len(fake)} generated competition(s): "
              + ", ".join(sorted(str(l) for _s, l in fake)))
    quiet, round_no, added, deadline = {}, 0, 0, time.time() + args.minutes * 60
    while True:
        round_no += 1
        done, counts = sweep(state, ids, quiet, round_no, fake)
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
