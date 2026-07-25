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
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

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
    v = get(f"Get1x2_VZip?sports={sid}&champs={champ}&count=200&lng=en&mode=4"
            f"&partner={partner}&getEmpty=true") or []
    return [(g.get("CI"), g.get("S")) for g in v if g.get("CI")]


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
    in_window = {}
    total_seen = 0
    for lst in fx_lists:
        for ci, s in lst:
            total_seen += 1
            if s and now <= s <= until:
                in_window[ci] = s
    print(f"fixtures seen: {total_seen} | starting within {args.hours}h: {len(in_window)}",
          flush=True)

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

    # Sub-games only with leftover budget - the main card outranks them.
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
