"""Scanner configuration. Single-book mode — no reference book."""

# The book to scan. Coverage on your OddsPapi key is UNCONFIRMED until the probe runs.
BOOK = "betwinner"

# Tournaments to pull. Use ones with open fixtures (upcomingFixtures/liveFixtures > 0).
#   34480 = UEFA Conference League   390 = Brazil Serie B   325 = Brazil Serie A
# EPL (17) is off-season -> ~94% markets closed.
TOURNAMENTS = [34480]

# --- Hard filters -----------------------------------------------------------
STALENESS_MINUTES = 15          # drop selections whose line is older than this,
                                # measured relative to the freshest line in the pull
INCLUDE_ALT_LINES = False       # False = main line only; True = include alternative lines
ALLOWED_MARKET_TYPES = None     # None = all; or e.g. {"moneyline", "totals", "spreads"}

# --- Composite score --------------------------------------------------------
# Each component is 0..1. Weights are PROVISIONAL — tune against the first real
# Betwinner fixture. If Betwinner returns no `limit`, the limit component disables
# and its weight is redistributed proportionally to the others.
WEIGHTS = {
    "margin": 0.5,   # lower per-market hold -> higher score
    "limit":  0.3,   # higher limit -> higher score (auto-disables if limit absent)
    "range":  0.2,   # closeness to ODDS_RANGE
}
ODDS_RANGE = (1.50, 2.50)       # plateau band for range_score
RANGE_DECAY = 1.00              # decimal-odds distance over which range_score fades to 0

# --- Output -----------------------------------------------------------------
TOP_N = 50
REPORT_PATH = "report.json"
