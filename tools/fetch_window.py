#!/usr/bin/env python3
"""Pull every pre-match Betwinner market starting inside a time window.

    python tools/fetch_window.py --hours 48 --out data/betwinner_48h.json.gz

Walks sports -> tournaments -> fixtures -> full market list, keeping only fixtures
that start inside the window. Standard library only; the project takes no pip
dependencies.

Notes paid for the hard way:
  * partner=51 is 1xBet's id and returns ZERO sports on betwinner.com. Betwinner's own
    ids (159, 169, …) return the full line. This is not geo-blocking.
  * countevents caps the market list. At 250 a fixture came back with 21 groups / 307
    priced selections; at 1000 it returns 119 groups / 847. 5000 matches 1000, so the
    line saturates there.
  * Sub-games ("First To Happen", halves, corners) are separate game ids. The parent
    fixture carries only references, so their markets have to be fetched separately.
  * count= on Get1x2_VZip is capped around 50 regardless of what you ask for, which is
    why fixtures are enumerated per tournament rather than per sport.

LIVE (in-play) markets are NOT covered. LineFeed is the pre-match feed; in-play sits
behind different endpoints.
"""
import argparse
import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402

BASE = "https://betwinner.com/service-api/LineFeed"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126 Safari/537.36")
COUNTEVENTS = 1000


def get(path, tries=2, timeout=12):
    """GET a LineFeed endpoint, returning the decoded Value or None."""
    url = f"{BASE}/{path}"
    for attempt in range(tries):
        try:
            req = urllib.request.Request(
                url, headers={"Accept": "application/json", "User-Agent": UA}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8", "replace"))
            if body.get("Success") is False:
                return None
            return body.get("Value")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            if attempt == tries - 1:
                return None
            time.sleep(1.0)
    return None


def sports(partner):
    v = get(f"GetSportsShortZip?lng=en&partner={partner}&virtualSports=true&gr=70") or []
    seen, out = set(), []
    for s in v:
        sid = s.get("I")
        if sid and sid not in seen:
            seen.add(sid)
            out.append((sid, s.get("N") or str(sid)))
    return out


def champs(sid, partner):
    v = get(f"GetChampsZip?sport={sid}&lng=en&partner={partner}"
            f"&virtualSports=true&groupChamps=true") or []
    ids = []
    for c in v:
        if c.get("LI"):
            ids.append(c["LI"])
        # A grouped champ hides its real tournaments in SC; without descending into
        # them whole competitions go missing from the sweep.
        for sub in c.get("SC") or []:
            if sub.get("LI"):
                ids.append(sub["LI"])
    return ids


def fixtures(champ, sid, partner):
    """(game id, start, is head-to-head) for one tournament.

    The third value is hard rule 7 applied where it is FREE. An entry with no second
    participant is not a head-to-head — that one test removes tournament winners, top
    scorers, election questions, novelty bundles and every multi-runner race at once — and
    the tournament listing already says so, in `O2`. It used to be applied after the full
    market list had been pulled for each of them, which on a live card meant fetching every
    horse in every race and every lottery draw at a thousand events apiece, then discarding
    all of it. The rule has not changed; it is just enforced before the expensive part.
    """
    v = get(f"Get1x2_VZip?sports={sid}&champs={champ}&count=200&lng=en&mode=4"
            f"&partner={partner}&getEmpty=true") or []
    return [(g.get("CI"), g.get("S"), bool(g.get("O2"))) for g in v if g.get("CI")]


def skipped_path(out):
    """Where the "what we did not fetch" note sits, next to the card it describes.

    One definition, imported by the reader, so the writer and the reader cannot drift
    into two different filenames and silently report an empty card as a complete one.
    """
    return os.path.splitext(out)[0] + ".skipped.json"


def game(ci, partner):
    return get(f"GetGameZip?id={ci}&lng=en&cfview=0&isSubGames=true&GroupEvents=true"
               f"&countevents={COUNTEVENTS}&partner={partner}&grMode=4&country=1"
               f"&marketType=1")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=48.0)
    ap.add_argument("--partner", default="159")
    ap.add_argument("--out", default="data/betwinner_48h.json.gz")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--sports", default="", help="csv of sport ids; blank = every sport")
    ap.add_argument("--max-fixtures", type=int, default=0, help="0 = no cap")
    ap.add_argument("--budget-min", type=float, default=150.0,
                    help="wall-clock budget in minutes; stops gracefully and writes what it has")
    ap.add_argument("--sub-games", action="store_true",
                    help="also pull halves, corners and 'first to happen' (nothing in the "
                         "daily product reads these)")
    ap.add_argument("--keep-outrights", action="store_true",
                    help="do not apply hard rule 7 at enumeration time")
    args = ap.parse_args()

    now = time.time()
    until = now + args.hours * 3600
    deadline = now + args.budget_min * 60
    pool = ThreadPoolExecutor(max_workers=args.workers)

    collected = []

    def flush(note=""):
        """Write everything collected so far. Called periodically, so a timeout kill
        costs at most one checkpoint interval, not the whole run."""
        payload = json.dumps(collected).encode()
        if args.out.endswith(".gz"):
            with gzip.open(args.out, "wb") as f:
                f.write(payload)
        else:
            with open(args.out, "wb") as f:
                f.write(payload)
        print(f"checkpoint: {len(collected)} records "
              f"({len(payload) / 1024 / 1024:.1f} MB){' - ' + note if note else ''}",
              flush=True)

    if args.sports.strip():
        sport_list = [(int(x), f"sport{x}") for x in args.sports.split(",") if x.strip()]
    else:
        sport_list = sports(args.partner)
    print(f"sports: {len(sport_list)}", flush=True)

    champ_lists = list(pool.map(lambda s: champs(s[0], args.partner), sport_list))
    pairs = [(c, sid) for (sid, _), cl in zip(sport_list, champ_lists) for c in cl]
    print(f"tournaments: {len(pairs)}", flush=True)

    fx_lists = list(pool.map(lambda p: fixtures(p[0], p[1], args.partner), pairs))
    # A fixture can be listed under several tournaments; dedupe on the game id, and
    # keep only what starts inside the window. Starts slightly in the past are dropped
    # rather than trusted — that is in-play territory and this is a pre-match pull.
    #
    # THE TWO RULES BELOW WERE ALWAYS IN FORCE — they were simply applied after the whole
    # market list had been pulled for each fixture and then discarded. On a live 48-hour
    # card that was 549 of 1,745 fixtures fetched at a thousand events apiece purely to
    # throw them away: 281 lottery draws, 254 horses and greyhounds, 14 crypto derivatives.
    # Applying them at enumeration costs nothing and is the same product.
    excluded = getattr(config, "EXCLUDED_SPORTS", set())
    in_window, skipped = {}, {"excluded_sport": {}, "not_head_to_head": {}}
    total_seen = 0
    for (_champ, sid), lst in zip(pairs, fx_lists):
        for ci, s, h2h in lst:
            total_seen += 1
            if not s or not (now <= s <= until) or ci in in_window:
                continue
            if sid in excluded:
                skipped["excluded_sport"][sid] = skipped["excluded_sport"].get(sid, 0) + 1
                continue
            if not h2h and not args.keep_outrights:
                skipped["not_head_to_head"][sid] = (
                    skipped["not_head_to_head"].get(sid, 0) + 1)
                continue
            in_window[ci] = s
    dropped = sum(sum(v.values()) for v in skipped.values())
    print(f"fixtures seen: {total_seen} | starting within {args.hours}h: "
          f"{len(in_window) + dropped} | to fetch: {len(in_window)} "
          f"(dropped {dropped}: "
          f"{sum(skipped['excluded_sport'].values())} excluded sport, "
          f"{sum(skipped['not_head_to_head'].values())} not head-to-head)", flush=True)
    # Written next to the card so the daily coverage report can still say what was on it
    # and why it was left out. A gap that is reported every day is a decision; a gap you
    # trip over is a surprise, and this filter would otherwise make those sports vanish
    # silently rather than be listed as excluded.
    try:
        with open(skipped_path(args.out), "w") as f:
            json.dump(skipped, f)
    except OSError:
        pass

    ids = sorted(in_window, key=lambda c: in_window[c])
    if args.max_fixtures:
        ids = ids[: args.max_fixtures]
        print(f"capped to {len(ids)} fixtures", flush=True)

    CHUNK = 200
    timed_out = False
    for i in range(0, len(ids), CHUNK):
        if time.time() > deadline:
            print(f"budget exhausted after {len(collected)} fixtures - stopping early",
                  flush=True)
            timed_out = True
            break
        chunk = ids[i:i + CHUNK]
        got = [g for g in pool.map(lambda c: game(c, args.partner), chunk)
               if isinstance(g, dict) and g.get("GE")]
        collected.extend(got)
        flush(f"fixtures {i + len(chunk)}/{len(ids)}")
    print(f"fixtures fetched: {len(collected)}", flush=True)

    # Sub-games — halves, corners, "first to happen" — are OPT-IN, because nothing in the
    # daily product reads one. engine/pick.py drops them (full-match probabilities do not
    # describe a half, and pricing one with the other produced edges above +1.0 before it
    # was caught) and engine/edge.py drops them again. They were 365,329 of the 674,379
    # rows on a real card: 54% of the payload, fetched and normalized to be skipped.
    sub_ids = set()
    if args.sub_games:
        sub_ids = {sg["CI"] for g in collected for sg in (g.get("SG") or []) if sg.get("CI")}
        sub_ids -= set(ids)
    subs_done = 0
    if sub_ids and not timed_out:
        sub_list = sorted(sub_ids)
        for i in range(0, len(sub_list), CHUNK):
            if time.time() > deadline:
                print("budget exhausted during sub-games - stopping early", flush=True)
                break
            chunk = sub_list[i:i + CHUNK]
            got = [g for g in pool.map(lambda c: game(c, args.partner), chunk)
                   if isinstance(g, dict) and g.get("GE")]
            collected.extend(got)
            subs_done += len(got)
            flush(f"sub-games {i + len(chunk)}/{len(sub_list)}")
    print(f"sub-games fetched: {subs_done} of {len(sub_ids)} referenced", flush=True)

    out = collected
    sel = sum(
        1
        for g in out
        for grp in g.get("GE") or []
        for row in grp.get("E") or []
        for e in (row if isinstance(row, list) else [row])
        if isinstance(e, dict) and e.get("C")
    )
    print(f"records: {len(out)} | market groups: {sum(len(g.get('GE') or []) for g in out)}"
          f" | priced selections: {sel}", flush=True)

    flush("final")
    return 0 if out else 1


if __name__ == "__main__":
    sys.exit(main())
