#!/usr/bin/env python3
"""Probe every catalogued data source and write data/source_health.json.

    python tools/check_source_health.py

Qualifies each source on its BODY, never its status code (hard rule 10 — a 200 has been
a Cloudflare block page, an Incapsula challenge, or an empty placeholder before). A
network failure or an unexpected body marks a source `degraded`/`unavailable`; it never
raises and never fails the run that calls it — this is diagnostic, not load-bearing.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

UA = "bw-scanner/1.0 (source health check; contact via repo)"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "data", "source_health.json")


def _fetch(url, timeout=15):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(4000)
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception as e:                                    # noqa: BLE001 — diagnostic
        return None, str(e).encode()


def _check(name, url, body_marker, category):
    t0 = time.time()
    status, body = _fetch(url)
    elapsed = round(time.time() - t0, 2)
    text = body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body)
    ok = status == 200 and body_marker in text
    if status == 200 and not ok:
        state = "degraded"           # 200 but not the body we expect — hard rule 10
    elif ok:
        state = "ok"
    else:
        state = "unavailable"
    return {
        "name": name, "category": category, "url": url, "state": state,
        "http_status": status, "elapsed_seconds": elapsed,
        "checked_at": _now(),
    }


def _now():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


SOURCES = (
    ("clubelo", "http://api.clubelo.com/Barcelona", "Rank,Club,Country,Level,Elo", "football"),
    ("football-data.co.uk", "https://www.football-data.co.uk/mmz4281/2526/E0.csv",
     "Div,Date", "football"),
    ("tml-database", "https://raw.githubusercontent.com/Tennismylife/TML-Database/master/2024.csv",
     "winner_name", "tennis"),
    ("tennisexplorer.com", "https://www.tennisexplorer.com/robots.txt", "User-agent", "tennis"),
    ("tennis-data.co.uk", "https://www.tennis-data.co.uk/2026/2026.csv", "Surface", "tennis"),
    ("open-meteo", "https://api.open-meteo.com/v1/elevation?latitude=41&longitude=29",
     "elevation", "weather"),
)


def main():
    results = [_check(*s) for s in SOURCES]

    # Betwinner itself: resolved through the mirror, same as the live pipeline does — a
    # SEPARATE check from the catalogue above because it is not a URL you fetch directly,
    # it is a rotating host you resolve first.
    try:
        import config
        from engine import mirror
        host, source = mirror.current(getattr(config, "REFERRAL_URL", None))
        results.append({
            "name": "betwinner", "category": "odds", "url": f"https://{host}" if host else None,
            "state": "ok" if host else "unavailable", "http_status": None,
            "elapsed_seconds": None, "checked_at": _now(),
            "detail": f"mirror resolution: {source}",
        })
    except Exception as e:                                     # noqa: BLE001
        results.append({"name": "betwinner", "category": "odds", "url": None,
                       "state": "unavailable", "checked_at": _now(), "detail": str(e)})

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    payload = {"checked_at": _now(), "sources": results}
    with open(OUT, "w") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    for r in results:
        print(f"  {r['name']:<22} {r['state']:<12} {r.get('http_status')}")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
