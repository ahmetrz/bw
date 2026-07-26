"""Resolve Betwinner's currently reachable domain.

The book is blocked in Turkey and answers by rotating its public domain, so a link built
on a hardcoded host is a link that eventually stops opening. The operator's referral link
is the stable entry point: it always lands on whichever mirror is live right now.

Resolving it takes two hops, and the first one is not an HTTP redirect. The referral page
answers 200 with a JavaScript `window.location.href` pointing at its own
`redirector.html`; only that second URL issues real 30x redirects to the live host. A
plain redirect-following client stops at the first page and learns nothing, which is why
the JS target is parsed out explicitly.

The result is cached with a timestamp, because this runs once per report and the domain
does not rotate by the minute. A failed resolution falls back to the last known good host
rather than to nothing: a stale mirror is far more useful than no link at all, and the
report says which one it used.
"""
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

CACHE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "mirror.json"
)

# Betwinner's own canonical host. It currently redirects to the live mirror itself, so it
# is a sane fallback — but it is the host Turkish ISPs block, hence the referral hop.
FALLBACK = "betwinner.com"

UA = ("Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126 Mobile Safari/537.36")

MAX_AGE_SECONDS = 6 * 3600


def _fetch(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.geturl(), r.read().decode("utf-8", "replace")


def resolve(referral_url, timeout=25):
    """Follow the referral link to the live host. Returns a hostname, or None."""
    if not referral_url:
        return None
    try:
        final, body = _fetch(referral_url, timeout)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None

    # Hop one: the JS redirect. Nothing else on that page names the destination.
    hop = re.search(r"location\.href\s*=\s*['\"]([^'\"]+)['\"]", body)
    if hop:
        target = urllib.parse.urljoin(final, hop.group(1))
        try:
            final, _ = _fetch(target, timeout)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
            pass

    host = urllib.parse.urlparse(final).netloc.lower()
    if not host or "redirector" in final and host in referral_url:
        return None
    # A host that is still the referral shortener means the hop did not complete.
    if host and urllib.parse.urlparse(referral_url).netloc.lower() == host:
        return None
    return host or None


def _read_cache():
    try:
        with open(CACHE) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def current(referral_url=None, max_age=MAX_AGE_SECONDS, force=False):
    """The host to build links on, resolving if the cache is stale.

    Returns (host, source) where source is one of resolved / cached / fallback, so the
    caller can say which one it used rather than implying a fresh lookup every time.
    """
    cached = _read_cache()
    age = time.time() - (cached.get("checked_at") or 0)
    if not force and cached.get("host") and age < max_age:
        return cached["host"], "cached"

    host = resolve(referral_url) if referral_url else None
    if host:
        os.makedirs(os.path.dirname(CACHE) or ".", exist_ok=True)
        with open(CACHE, "w") as f:
            json.dump({"host": host, "checked_at": time.time(),
                       "referral": referral_url}, f, indent=1)
        return host, "resolved"
    if cached.get("host"):
        return cached["host"], "cached"
    return FALLBACK, "fallback"


def event_url(host, sport_id, champ_id, game_id, lang="en"):
    """Deep link to one fixture on the live mirror.

    The numeric path is used deliberately: the book redirects it to its own slugged form
    ("/en/line/1/67559-club-friendlies/354178770-napoli-carrarese-calcio"), so the link
    resolves without us having to know or guess a competition slug.
    """
    if not (host and sport_id and champ_id and game_id):
        return None
    return f"https://{host}/{lang}/line/{sport_id}/{champ_id}/{game_id}"
