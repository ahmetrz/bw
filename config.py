"""Scanner configuration. Single-book mode — no reference book."""

# The book to scan. Coverage on your OddsPapi key is UNCONFIRMED until the probe runs.
BOOK = "betwinner"

# Tournaments to pull. Use ones with open fixtures (upcomingFixtures/liveFixtures > 0).
#   34480 = UEFA Conference League   390 = Brazil Serie B   325 = Brazil Serie A
# EPL (17) is off-season -> ~94% markets closed.
TOURNAMENTS = [34480]

# --- Hard filters -----------------------------------------------------------
# Drop markets whose hold exceeds this. The first real Betwinner pull carried holds up
# to 233.9%, with 109 markets over 100% — correct-score and similar exotics. Those are
# not selections worth ranking, and because each carries dozens of outcomes they also
# dominate any distribution computed over rows. Set to None to keep everything.
MAX_OVERROUND = 0.25
STALENESS_MINUTES = 15          # drop selections whose line is older than this,
                                # measured relative to the freshest line in the pull
INCLUDE_ALT_LINES = False       # False = main line only; True = include alternative lines
ALLOWED_MARKET_TYPES = None     # None = all; or e.g. {"moneyline", "totals", "spreads"}

# --- Composite score --------------------------------------------------------
# Each component is 0..1. Weights are PROVISIONAL — tune against the first real
# Betwinner fixture. If Betwinner returns no `limit`, the limit component disables
# and its weight is redistributed proportionally to the others.
WEIGHTS = {
    "margin": 0.70,  # lower per-market hold -> higher score
    "range":  0.30,  # closeness to ODDS_RANGE
}
# `limit` is deliberately absent. Betwinner's line feed publishes no stake limit, so the
# component was never live — it was declared at 0.3 and silently redistributed, leaving
# an effective 0.714/0.286 that no one had chosen. These are the weights that actually
# apply. If a source that DOES carry limits is added, put the key back and re-tune;
# leaving it out means limit data would be read and then ignored.

# Normalize the hold WITHIN each market type rather than across the whole run.
# Comparing a totals hold to a 1X2 hold compares different products: on the first real
# pull, totals started at 6.38% while no moneyline market priced below 7.27%, so a
# single global scale ranked every totals market above every 1X2 and the top 50 came
# back 100% totals under every weighting tried — including margin 1.0 / range 0.0.
# Per-type normalization asks the answerable question instead: how cheap is this market
# against others of its own kind. Types with fewer than MIN_MARKETS_PER_TYPE distinct
# markets fall back to the global scale, since a type with one or two markets would
# otherwise normalize flat and score every one of its selections 1.0.
MARGIN_NORM_PER_TYPE = True
MIN_MARKETS_PER_TYPE = 5
ODDS_RANGE = (1.50, 2.50)       # plateau band for range_score
RANGE_DECAY = 1.00              # decimal-odds distance over which range_score fades to 0

# --- Diversity --------------------------------------------------------------
# Under proportional de-vig the margin signal is per-MARKET, and every market inside one
# fixture tends to share a similar hold. So without a cap a single low-hold fixture
# sweeps the ranking — the first real Betwinner run filled its entire top 24 from one
# match. This caps how many selections one fixture may contribute to the emitted top-N.
# Set to 0 to disable and rank purely on score.
MAX_PER_FIXTURE = 4

# --- Output -----------------------------------------------------------------
TOP_N = 50
REPORT_PATH = "report.json"
