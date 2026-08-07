# SECURITY.md

This is a single-operator batch pipeline: it fetches from a small, hardcoded list of
sources, writes JSON and self-contained HTML files, and pushes them to a git repo or a
Telegram chat. It has no server process handling requests from anyone, no login, and no
concept of a session. That shape determines most of what's below — several sections of a
typical checklist are answered "not applicable" here, and this document says so directly
rather than filling the gap with a control for a threat that doesn't exist in this
architecture.

## Secret handling

Every credential this project uses is read from an environment variable and nothing
else — `os.environ.get(...)`, never a config file, never a CLI flag:

- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` (`engine/telegram.py`'s `credentials()`)
- `ODDSPAPI_KEY` and the ten candidate names `probe-oddsapi-io.yml` sweeps (legacy/probe
  workflows only — nothing in the daily pipeline reads these)

**A missing secret is a valid, non-fatal state, not an error.** `engine/telegram.py`'s
`configured()` returns `False` and `send()`/`send_document()` return
`(False, "... not set — notification skipped")` — the calling script continues and the
run completes normally (`CLAUDE.md`'s "Secrets" section states this as policy;
`tools/telegram_ping.py`'s own docstring states the reasoning: "a missing token is a
valid state — the daily run still scans and still writes its report, it just cannot
notify"). `combine.yml`'s "Check Telegram credentials" step runs `telegram_ping.py --quiet`
before the expensive fetch specifically so a **present but broken** token — a genuine
fault — surfaces in seconds rather than after the fetch has nowhere to send its
result; that script exits 0 when credentials are simply absent and 1 only when they're
set and fail.

**Secrets are never logged.** `telegram_ping.py` prints only presence/absence
("Telegram: credentials present" / "not configured"), never the value. The
`probe-oddsapi-io.yml` and `probe-odds.yml` workflows, which print request URLs for
debugging, explicitly mask the key in every printed URL
(`apiKey=***` — see `docs/GITHUB_ACTIONS.md`); `fetch-odds.yml` builds the same kind of
URL but never echoes it at all. Nothing in this codebase constructs a log line by
interpolating a secret into it.

## Output encoding

Every HTML page this project generates is built by Python string formatting, not a
templating engine with autoescaping — so escaping is manual. All 14 platform pages go
through one shared helper: `tools/webshell.py`'s `esc(v)`
(`html.escape(str(v), quote=True)`), used at every dynamic interpolation point across
`tools/make_platform_pages.py`. One template, one escaping path, by design — a second,
independently-formatted page generator would be a second chance to get escaping wrong
(`docs/ARCHITECTURE.md`).

This used to be two independent escaping paths, kept apart on purpose while a second,
now-retired product shared this repo: the old scanner's own pages (`picks.html`,
`results.html`, `stats.html`, `method.html`, rendered by `tools/make_picks_page.py`,
`tools/make_stats_page.py`, `tools/make_method_page.py`, each calling `html.escape()`
inline at its own interpolation points) were kept separate from the new platform's shared
`webshell.py` helper specifically so touching one code path never risked the other's
test coverage. Those tools and pages were deleted with the scanner
(`docs/DECISIONS/0007`), so `webshell.py`'s `esc()` is the only escaping path left; both
it and the retired pages' inline calls always quoted attribute values
(`quote=True` / `html.escape`'s default), so escaped text was safe in both element content
and attribute position either way.

The one place a dynamic value used to be embedded directly into inline JavaScript rather
than into HTML — the retired `picks.html`'s client-side filter script, which read a `DAY`
value — used `json.dumps()` to produce the literal, not an f-string. That was the correct
technique for landing a string safely inside a `<script>` block, since HTML-escaping alone
does not make a value safe inside a JS string literal; nothing in the surviving 14 pages
currently embeds a dynamic value into inline JavaScript the same way, but the technique is
worth keeping in mind if one ever does.

Every generated page is also a single self-contained file: no CDN script, no external
font, no analytics, no `<script src=` (`webshell.py`'s stated design constraint, matched
by the old pages too). That's motivated by the pages needing to open from a phone, often
offline, from a Telegram attachment — but it also means there is no third-party script
origin on any generated page to compromise.

## SSRF / path traversal: structurally not applicable here

This is stated plainly rather than described as "mitigated," because there is no
attacker-controlled input in the position that would make either threat real:

- **Every outbound fetch target is a hardcoded literal in source, not a URL built from
  external input.** `tools/check_source_health.py`'s `SOURCES` tuple, `engine/bwfeed.py`
  / `engine/coupon.py` / `engine/mirror.py`'s Betwinner endpoint bases, and
  `tools/collect_results.py`'s per-adapter base URLs (`FD_BASE`,
  `raw.githubusercontent.com/...`, `tennisexplorer.com`, ...) are all written directly into
  the `.py` files. Nothing in this project accepts a URL from a request, a form, or any
  other untrusted party and then fetches it — there is no code path where that could even
  be wired up, because there is no request-handling surface at all. Classic SSRF assumes
  a service that fetches a URL on a caller's behalf; that shape doesn't exist here.
- **`--input` takes a local filesystem path, read with `open()`/`gzip.open()`, never a
  URL.** The party who supplies that path is whoever invokes the CLI or fills in a
  `workflow_dispatch` form field — the operator themselves, or GitHub's own Actions
  config — not a remote, untrusted caller crossing a network boundary. There is no
  scenario in this project's actual usage where an external party controls a path that
  reaches `open()`.

Nothing here needed a mitigation because nothing here has the shape that creates the
risk. If this project ever grows a component that fetches a URL supplied by someone other
than the operator, that would be a new attack surface requiring new controls — it is not
what exists today.

## Dependency posture

The core pipeline — `engine/`, `tools/daily_combine.py`, every collector, the model
fitter, every page generator except the PDF one — is standard library only
(`requirements.txt`'s own header comment;
verified by `tests/test_regression.py` running with zero installs). The **one** pinned
dependency is `reportlab>=4.0,<5.1`, used exclusively by `tools/make_pdf_report.py`. No
lockfile, no transitive dependency tree to audit beyond what PyPI resolves for that one
package, and the constraint is a version range, not an unpinned `reportlab` that could
pull in an untested major version.

## What's explicitly not implemented, and why that's correct here

- **No authentication or session system, anywhere.** There is no login form, no cookie,
  no session token, nothing that identifies "a user" as distinct from "whoever has the
  repo or the Telegram chat." This is a single-operator personal tool (`CLAUDE.md`,
  `docs/DATA_LICENSING.md`'s framing throughout) — there is no multi-user surface for an
  auth system to protect.
- **CSRF, session fixation, and related session-security checklist items are N/A**, for
  the same reason: they are properties of a stateful web session, and nothing in this
  project holds one. Saying "not applicable" here is the accurate answer, not an omission
  — building CSRF protection into a batch script with no HTTP server would be adding a
  control with nothing behind it to protect.
- **The generated pages have no access control**, because the repo they're committed to
  is public (`docs/DATA_SOURCES.md`: "the repo is public, Actions minutes are
  unlimited") — anyone with the repo URL can read `combine.html` and every other platform
  page this pipeline writes, same as any other file in a public repo. That is
  a consequence of the operator's own hosting choice (public repo, unlimited Actions
  minutes, per that same source) rather than a gap this project should close — the pages
  contain no credentials and no personal data beyond the operator's own betting selections,
  and in practice the intended reader is whoever the Telegram bot messages.

## The CI secret-pattern check (`tests.yml`)

New this session, described in full in `docs/GITHUB_ACTIONS.md`. One step greps every
tracked file (excluding `*.md` and `tests/*`) for the shape of a real Telegram bot token
(`[0-9]{6,10}:[A-Za-z0-9_-]{35}`) and fails the build on a match. The workflow's own
comment is explicit about its scope: this is **defense in depth, not the primary
control** — "GitHub's own secret scanning already covers public repos, this is a second,
narrower check." It catches exactly one credential shape by exact regex; it is not a
general secret scanner, doesn't cover `ODDSPAPI_KEY` or any other secret format (those
have no fixed, greppable shape the way a Telegram token does), and isn't presented here
as more than what it is.

## What this document deliberately does not include

Rate limiting, WAF rules, input sanitization against SQL/command injection (there is no
database and no shell command built from external input), and encryption-at-rest
guidance are absent because none of them address a real path through this codebase — the
task brief for this document was to describe the actual posture of a single-operator,
static-page-generating batch pipeline, not to pad a checklist with controls for a
different kind of system.
