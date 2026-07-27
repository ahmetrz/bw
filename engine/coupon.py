"""Turn the day's selections into ONE Betwinner bet-slip code.

    from engine import coupon
    code, detail = coupon.create(picks)      # -> "TX9PR"

The operator types that code into the book's "load bet slip" box and every selection
appears at once, instead of opening thirty fixtures and finding thirty markets by hand.

HOW THIS WAS FOUND, because the earlier answer in this repo was "there is no way".
`/en/user/coupon` redirects to login, every coupon path guessed by name 404s, and the
site's real UI lives on a mirror whose robots.txt is `Disallow: /`. What was missing was
that the host application's lazy chunks are served from betwinner.com itself, under
`/sys-static/sys-v3-host-app-static/Desktop/BetWinner/`. All 331 of them fetch cleanly,
and one carries the route table:

    POST /service-api/LiveBet/Open/SaveCoupon   -> {"Value": "<code>", "Success": true}
    POST /service-api/LiveBet/Open/GetCoupon    -> the slip behind a code

Neither is marked `isUseXAuth` in that table, and neither needs a session. They are the
book's own share-a-slip feature, which is exactly what we want: we are not placing a bet
or touching an account, we are writing a slip and handing over its code.

TWO DETAILS COST AN HOUR EACH AND BOTH FAIL SILENTLY IF WRONG.

  * THE GAME ID IS `I`, NOT `CI`. The feed publishes both. `CI` is the constant id the
    deep link uses and what `fixture_id` holds; `I` is what the slip keys on. Send `CI`
    and the service answers "Events in the downloaded bet slip have finished" — which
    reads like a stale card and actually means an id it does not know.

  * THE LINE IS FROM THE BACKED SIDE'S VIEW. engine/bwfeed normalizes handicaps to the
    line as the HOME side sees them, so that both sides of one market share a key and the
    hold is computable. The slip wants what the feed originally published for that
    outcome. Backing Cuiaba +1.5 at 1.197 and sending -1.5 produced a slip the book
    priced at 9.00 — the opposite handicap, silently, at a price nobody would take.

So the code is verified before it is handed over: the slip is read back and every leg's
price compared against the price the pick was made at. A slip that does not match is not
offered, because a wrong slip loaded in one tap is worse than no slip at all.
"""
import json
import urllib.error
import urllib.request

from engine import bwfeed

BASE = "https://betwinner.com/service-api/LiveBet/Open"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126 Safari/537.36")

# Pre-match events are Kind 3; live ones are Kind 1. Everything this product emits is
# pre-match by construction — hard rule 7 — so there is one value here and it is stated
# rather than passed around.
KIND_PREMATCH = 3

# How far a leg's price may have moved between the pick and the slip before the slip is
# refused. Odds drift between the morning fetch and the operator loading it; a leg that
# has moved further than this is more likely the WRONG leg than a repriced one.
MAX_PRICE_DRIFT = 0.25


def _post(path, body, timeout=25):
    req = urllib.request.Request(
        f"{BASE}/{path}", data=json.dumps(body).encode(),
        headers={"User-Agent": UA, "Content-Type": "application/json",
                 "Accept": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read() or b"{}")
        except (ValueError, OSError):
            return {"Success": False, "Error": f"HTTP {e.code}"}
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        return {"Success": False, "Error": str(e)[:120]}


def event_of(pick):
    """One slip event from one emitted selection, or None if it cannot be expressed."""
    game_id = pick.get("game_id")
    outcome = pick.get("outcome_id")
    if not game_id or not outcome:
        return None
    try:
        group, _, line = str(pick["market_key"][1]).partition("|")
        group = int(group)
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    try:
        param = float(line)
    except (TypeError, ValueError):
        param = 0.0
    # Back out bwfeed's home-side normalization: the slip wants the line as the BACKED
    # side sees it, which is what the feed published before we re-keyed it.
    home_outcome = bwfeed.HANDICAP_HOME_SIDE.get(group)
    if home_outcome is not None and outcome != home_outcome:
        param = -param
    return {"GameId": int(game_id), "Type": int(outcome), "Coef": float(pick["odds"]),
            "Param": param, "Kind": KIND_PREMATCH, "PlayerId": 0, "InstanceId": 0}


def create(picks, verify=True):
    """(code, detail) for a slip holding these selections, or (None, why).

    `detail` reports how many legs the book accepted and how many it dropped, because it
    silently omits anything that has started or been suspended and the operator has to be
    told the slip is not the whole list.
    """
    events, skipped = [], 0
    for p in picks:
        ev = event_of(p)
        if ev:
            events.append(ev)
        else:
            skipped += 1
    if not events:
        return None, "kupona konulabilecek seçim yok"

    saved = _post("SaveCoupon", {"Events": events, "lng": "en", "partner": 159})
    code = saved.get("Value")
    if not saved.get("Success") or not code:
        return None, f"kupon kaydedilemedi: {saved.get('Error') or 'bilinmeyen hata'}"
    if not verify:
        return code, f"{len(events)} bahis"

    got = _post("GetCoupon", {"guid": code, "lng": "en", "partner": 159})
    if not got.get("Success"):
        return None, f"kupon geri okunamadı: {got.get('Error') or 'bilinmeyen hata'}"
    back = (got.get("Value") or {}).get("Events") or []

    # Every leg the book kept must be the leg we asked for, at the price we asked for.
    # This is the check that makes a one-tap slip safe to hand over: the handicap sign
    # bug produced a slip that loaded cleanly and held the OPPOSITE bet at 9.00.
    wanted = {(e["GameId"], e["Type"], round(e["Param"], 3)): e["Coef"] for e in events}
    mismatched = []
    for e in back:
        key = (e.get("GameId"), e.get("Type"), round(float(e.get("Param") or 0), 3))
        ours = wanted.get(key)
        theirs = e.get("Coef")
        if ours is None or theirs is None:
            mismatched.append(key)
        elif abs(float(theirs) - float(ours)) > MAX_PRICE_DRIFT:
            mismatched.append(key)
    if mismatched:
        return None, (f"kupon doğrulanamadı: {len(mismatched)} bahis istediğimizden "
                      f"farklı geldi, kod verilmiyor")

    dropped = len(events) - len(back)
    detail = f"{len(back)} bahis"
    if dropped > 0:
        detail += f" · {dropped} tanesi kitap tarafından alınmadı (başlamış veya kapalı)"
    if skipped:
        detail += f" · {skipped} seçim kupona çevrilemedi"
    return code, detail
