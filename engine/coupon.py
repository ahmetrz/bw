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

THREE DETAILS FAIL SILENTLY IF WRONG, AND THE THIRD REACHED THE OPERATOR.

  * THE GAME ID IS `I`, NOT `CI`. The feed publishes both. `CI` is the constant id the
    deep link uses and what `fixture_id` holds; `I` is what the slip keys on. Send `CI`
    and the service answers "Events in the downloaded bet slip have finished" — which
    reads like a stale card and actually means an id it does not know.

  * THE LINE IS FROM THE BACKED SIDE'S VIEW. engine/bwfeed normalizes handicaps to the
    line as the HOME side sees them, so that both sides of one market share a key and the
    hold is computable. The slip wants what the feed originally published for that
    outcome. Backing Cuiaba +1.5 at 1.197 and sending -1.5 produced a slip the book
    priced at 9.00 — the opposite handicap, silently, at a price nobody would take.

  * A SLIP THAT LOSES A LEG STOPS BEING SINGLES. This is the one that made the feature
    look broken for days after the bet type was fixed. Verifying at creation is not a
    guarantee that survives: the book does not FILTER a slip when a fixture starts, it
    REBUILDS it, and the rebuild takes the default bet type. Measured — five live legs
    saved as Vid=2 read back Vid=2 / Coef=0; the same five plus one started fixture read
    back Vid=1 / Coef=1.93 with HasRemoveEvents true. So a code minted at 06:43 and opened
    at midday has lost the legs that kicked off in between and arrives as an accumulator,
    correctly labelled "20 tekli bahis" by a page that checked it hours earlier. A coupon
    therefore has to be rebuilt from fixtures that have NOT started (tools/refresh_coupon.py),
    and codes expire anyway — every code from three days ago now answers "Incorrect code".

  * THE BET TYPE IS `Vid`, AND NOT SENDING IT MEANS ACCUMULATOR. This one shipped. The
    first slip the operator actually loaded was a twenty-leg combo at 85.19 — the product
    of all twenty prices — where one loss pays nothing on the other nineteen. The list it
    was built from is twenty independent equal stakes. Every leg was correct and the bet
    was wrong, which is why the price check alone did not catch it: it compared each leg
    and never asked what the slip as a whole WAS.

So the code is verified before it is handed over: the slip is read back, every leg's price
compared against the price the pick was made at, AND the bet type confirmed to be singles.
A slip that does not match is not offered, because a wrong slip loaded in one tap is worse
than no slip at all.
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

# THE SLIP'S BET TYPE, and getting this wrong loads a bet the product never recommended.
#
# `Vid` was not being sent at all, and the service defaults it to 1. Read back, a 20-leg
# slip saved that way returns `Coef: 85.190907` — the exact product of all twenty prices.
# That is an ACCUMULATOR: one leg loses and the whole day pays nothing. This product
# recommends twenty INDEPENDENT equal stakes (engine/stake.py), so the slip was loading
# the one bet the staking rule exists to rule out.
#
# Measured across 1, 2, 3, 4, 5 on the same three legs (product 1.4705):
#   Vid=1 -> Coef 1.470534  the product. Accumulator.
#   Vid=2 -> Coef 0         no combined price at all, which is what a set of singles has.
#   Vid=3 -> Coef 1.414     an average. System.
#   Vid=4 -> Coef 0
#   Vid=5 -> Coef 1.470534  the product again.
# Vid=0 is normalised to 1 by the service.
#
# So 2 is the singles mode, and the read-back CHECKS it rather than trusting it: a slip
# whose returned Vid is not 2, or which comes back carrying a combined coefficient, is
# refused. If the book ever renumbers these, that check turns a silently wrong bet type
# into no code at all, which is the failure this module is built to prefer.
VID_SINGLES = 2

# WHICH PARTNER THE SLIP IS SAVED UNDER, and this is what made the book say "Yanlış kod".
#
# A code is scoped to a partner. Saved under 159 — the id this project uses everywhere
# else, because it is the one that returns Betwinner's full line — `GetCoupon` answers
# "Incorrect code" / "Yanlış kod" for EVERY other partner id, and the operator's client
# is evidently not 159. That error is indistinguishable from a typo or an expired code
# from the outside, which is why it read as "the code is broken" rather than as a scope
# mismatch.
#
# Measured over partner ids 0-260, saving the same two legs each time:
#   saved under 159 -> readable by [159]
#   saved under 169 -> readable by [169]          (Betwinner's other id, same behaviour)
#   saved under 2   -> readable by [2]
#   saved under 1   -> readable by ~20 ids, INCLUDING 159, 7, 36, 55, 57, 61, 71, 76,
#                      89, 90, 104, 108, 132, 135, 156, 185, 234, 235, 243
# So 1 is the only value that does not bind the code to a single client, and it still
# covers the id we read the line with. Saving with no partner at all binds it to 0, which
# is worse: readable only by a client sending no partner.
#
# It is NOT proven that the operator's client is inside that set — it cannot be seen from
# here. What is proven is that 159 excluded everything except 159, so this strictly widens
# the door. If a code still comes back rejected, the operator's partner id is the one fact
# missing, and `COUPON_PARTNER` is where it goes.
COUPON_PARTNER = 1

# The partner we read the line with. The read-back checks the slip is visible to this one
# too, so a change in the book's scoping shows up as a refused code rather than as a code
# that silently only works somewhere we cannot see.
LINE_PARTNER = 159

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

    saved = _post("SaveCoupon", {"Events": events, "lng": "en",
                                 "partner": COUPON_PARTNER, "Vid": VID_SINGLES})
    code = saved.get("Value")
    if not saved.get("Success") or not code:
        return None, f"kupon kaydedilemedi: {saved.get('Error') or 'bilinmeyen hata'}"
    if not verify:
        return code, f"{len(events)} tekli bahis"

    got = _post("GetCoupon", {"guid": code, "lng": "en", "partner": COUPON_PARTNER})
    if not got.get("Success"):
        return None, f"kupon geri okunamadı: {got.get('Error') or 'bilinmeyen hata'}"
    # And visible to the partner we read the line with, which is a different client from
    # the one that wrote it. A code only its own author can open is the failure that
    # reached the operator, and it looked exactly like a broken code from their side.
    reach = _post("GetCoupon", {"guid": code, "lng": "en", "partner": LINE_PARTNER})
    if not reach.get("Success"):
        return None, (f"kupon yalnızca kendi partner'ıyla açılıyor "
                      f"({reach.get('Error') or 'okunamadı'}) — kod verilmiyor")
    value = got.get("Value") or {}
    back = value.get("Events") or []

    # THE BET TYPE IS CHECKED, not assumed. A combined coefficient coming back means the
    # book stored this as an accumulator or a system, and handing that over would load a
    # bet where one loss kills the other nineteen — the exact opposite of a flat plan.
    if value.get("Vid") != VID_SINGLES or float(value.get("Coef") or 0) != 0.0:
        return None, (f"kupon tekli olarak kaydedilmedi (Vid={value.get('Vid')}, "
                      f"Coef={value.get('Coef')}) — kod verilmiyor")

    # AND NOTHING MAY HAVE BEEN DROPPED, because dropping is what undoes the line above.
    # Measured: five live legs saved as Vid=2 read back Vid=2 / Coef=0; the same five plus
    # ONE started fixture read back Vid=1 / Coef=1.93 with HasRemoveEvents true. The book
    # does not filter the slip, it REBUILDS it, and the rebuild takes the default bet type.
    # So a slip that already lost a leg at creation is an accumulator whatever we asked
    # for, and this is the check that says so instead of shipping the label "tekli".
    if value.get("HasRemoveEvents"):
        return None, ("kupon bacak kaybetmiş — kitap kaybeden kuponu KOMBİNE olarak "
                      "yeniden kuruyor, kod verilmiyor")

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
    detail = f"{len(back)} tekli bahis"
    if dropped > 0:
        detail += f" · {dropped} tanesi kitap tarafından alınmadı (başlamış veya kapalı)"
    if skipped:
        detail += f" · {skipped} seçim kupona çevrilemedi"
    return code, detail
