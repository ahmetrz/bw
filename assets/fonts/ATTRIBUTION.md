# Font attribution

`DejaVuSans.ttf` and `DejaVuSans-Bold.ttf` are from the **DejaVu Fonts** project
(<https://dejavu-fonts.github.io/>), used here by `tools/make_pdf_report.py` because it
has full Turkish-character coverage (ç, ğ, ı, İ, ö, ş, ü and their capitals) — reportlab's
built-in Helvetica does not (it uses WinAnsi/cp1252 encoding, which is missing ğ, ı, ş).

Vendored into the repo rather than loaded from a system path so PDF generation does not
depend on which fonts happen to be installed on the GitHub Actions runner.

**License:** DejaVu fonts are derived from the Bitstream Vera fonts and distributed under
a permissive licence explicitly allowing embedding, modification and redistribution (no
royalty, no restriction on bundling with an application). Full authoritative licence text:
<https://dejavu-fonts.github.io/License.html>. Not reproduced verbatim here to avoid
transcription error — read it at the source before any reuse outside this repo.
