# Session 1 prompt — paste into Claude Code

```
Read CLAUDE.md and DATA_CONTRACT.md fully before doing anything.

This is a single-book Betwinner scanner. There is no reference book. The scanner
already exists (scan.py + engine/). Your Session 1 job is to VALIDATE it against real
data, not to rebuild it.

STEP 0 — coverage gate (blocking):
The probe-odds.yml workflow must have been run and Betwinner confirmed. If you cannot
confirm from data/ that a pull literally contains "betwinner", STOP and tell me — do
not proceed on cached/other-book data.

Then, in order:
1. Report what the probe found: is Betwinner covered? Does it return `limit`?
2. Take the first clean Betwinner pull in data/ and copy it to fixtures/sample.json.
3. Run: python scan.py --input fixtures/sample.json
   Confirm it prints a ranked top-50 table and writes report.json, with the book-
   mismatch warning silent (i.e. the data really is Betwinner).
4. Sanity-check the top 50: if it's all one market type or one match, the filters are
   wrong — fix engine/score.py.
5. Add a regression test that re-runs fixtures/sample.json and asserts the table is
   unchanged.
6. Report the limit-availability outcome and propose tuned config.WEIGHTS. Do not
   change weights silently — show me the before/after and wait.

Work autonomously, no step-by-step confirmation, but HALT at the human-in-the-loop
points in CLAUDE.md. Obey every hard rule. Default output is singles; only build a
parlay behind --parlay, and only in the book's own implied numbers with the caveat.
```
