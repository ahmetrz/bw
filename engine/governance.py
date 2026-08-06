"""Model governance: ProposedModelChange records, and immutable model-version archiving.

Two separate mechanisms, kept separate deliberately (see docs/DECISIONS/0004):

1. STRUCTURAL changes — a new weight, a new threshold, a new calibration METHOD, retiring
   a market or a league, changing which model is authoritative for a sport — are proposed
   here, never applied here. `propose()` writes one record; nothing in this codebase ever
   calls a matching `apply()`, because the platform brief is explicit: "İnsan onayı olmadan
   üretim modelini, eşikleri veya aktif kuralları değiştirme." A human reviews
   `data/proposed_changes.jsonl` (rendered on the "Önerilen Model Değişiklikleri" screen)
   and makes the change themselves, the same way any other code/config change in this repo
   is made — reviewed, committed, deployed.

2. ROUTINE recalibration — the existing daily `tools/build_generic_model.py --all` re-fit
   on newly accumulated results is NOT gated here. It is the same fitting METHOD run again
   on more data, automatically admitted or refused by its own held-out calibration check
   (hard rule 8) — a mechanism that already existed, was already live, and was already the
   product's whole answer to "how does a model get better." `archive_model_version()`
   below exists so that mechanism ALSO leaves an immutable trail and a rollback path,
   without requiring a human to approve each day's routine refresh.
"""
import datetime
import json
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROPOSALS_PATH = os.path.join(ROOT, "data", "proposed_changes.jsonl")
MODEL_HISTORY_DIR = os.path.join(ROOT, "data", "models", "history")

STATUS_PROPOSED, STATUS_APPROVED, STATUS_REJECTED = "proposed", "approved", "rejected"

CATEGORIES = (
    "weight_change", "threshold_change", "market_pause", "league_pause",
    "source_reliability_change", "new_feature", "module_disable",
    "calibration_method_change",
)


def _load_all():
    if not os.path.exists(PROPOSALS_PATH):
        return []
    out = []
    with open(PROPOSALS_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _save_all(rows):
    os.makedirs(os.path.dirname(PROPOSALS_PATH), exist_ok=True)
    with open(PROPOSALS_PATH, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def propose(proposal_id, category, title, description, evidence, current_value=None,
            proposed_value=None, requires_backtest=True, now=None):
    """Record a candidate change for human review. Idempotent on proposal_id — calling
    this again with the same id updates the existing record rather than duplicating it,
    so a recurring diagnostic (e.g. a daily coverage check) can re-propose the same
    finding without flooding the review queue."""
    if category not in CATEGORIES:
        raise ValueError(f"unknown category {category!r}")
    rows = _load_all()
    existing = next((r for r in rows if r["id"] == proposal_id), None)
    record = {
        "id": proposal_id, "category": category, "title": title,
        "description": description, "evidence": evidence,
        "current_value": current_value, "proposed_value": proposed_value,
        "requires_backtest": requires_backtest, "backtest_result": None,
        "status": STATUS_PROPOSED,
        "created_at": (now or _now()).isoformat(),
        "reviewed_by": None, "reviewed_at": None, "review_note": None,
    }
    if existing and existing["status"] != STATUS_PROPOSED:
        # A human already reviewed this id — do not silently resurrect it as pending.
        # Re-proposing something already rejected/approved needs a new id, which is the
        # honest way to say "this is a new instance of the finding," not the same
        # decision being overwritten out from under the reviewer.
        return existing
    if existing:
        record["created_at"] = existing["created_at"]   # keep original filing date
    rows = [r for r in rows if r["id"] != proposal_id] + [record]
    _save_all(rows)
    return record


def review(proposal_id, decision, reviewer, note=None, now=None):
    """Record a human decision. This is the ONLY place status changes away from
    'proposed' — and it still does not apply anything; it just says a human looked."""
    if decision not in (STATUS_APPROVED, STATUS_REJECTED):
        raise ValueError("decision must be approved or rejected")
    rows = _load_all()
    for r in rows:
        if r["id"] == proposal_id:
            r["status"] = decision
            r["reviewed_by"] = reviewer
            r["reviewed_at"] = (now or _now()).isoformat()
            r["review_note"] = note
            _save_all(rows)
            return r
    raise KeyError(f"no proposal {proposal_id!r}")


def list_proposals(status=None):
    rows = _load_all()
    if status:
        rows = [r for r in rows if r["status"] == status]
    return sorted(rows, key=lambda r: r["created_at"], reverse=True)


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


# --------------------------------------------------------------- model-version archive

def archive_model_version(sport_id, keep=30):
    """Copy the CURRENT data/models/<sport_id>.json to an immutable, timestamped path
    before it gets overwritten by the next fit. Call this BEFORE
    tools/build_generic_model.py writes a fresh model. Best-effort: a sport with no
    existing model file yet has nothing to archive, which is not an error.

    `keep` bounds how many past versions are retained per sport (oldest deleted first) —
    unbounded history of a file that refits daily would otherwise grow without limit.
    30 is roughly a month of daily refits, enough to roll back a recent regression without
    keeping years of near-duplicate snapshots.
    """
    src = os.path.join(ROOT, "data", "models", f"{int(sport_id)}.json")
    if not os.path.exists(src):
        return None
    with open(src) as f:
        model = json.load(f)
    stamp = model.get("last") or _now().date().isoformat()
    out_dir = os.path.join(MODEL_HISTORY_DIR, str(int(sport_id)))
    os.makedirs(out_dir, exist_ok=True)
    dest = os.path.join(out_dir, f"{stamp}_{model.get('games', 0)}g.json")
    if not os.path.exists(dest):
        shutil.copyfile(src, dest)
    versions = sorted(
        (f for f in os.listdir(out_dir) if f.endswith(".json")),
        key=lambda f: os.path.getmtime(os.path.join(out_dir, f)))
    for old in versions[:-keep]:
        os.remove(os.path.join(out_dir, old))
    return dest


def list_model_versions(sport_id):
    out_dir = os.path.join(MODEL_HISTORY_DIR, str(int(sport_id)))
    if not os.path.isdir(out_dir):
        return []
    versions = []
    for name in sorted(os.listdir(out_dir)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(out_dir, name)
        versions.append({
            "file": name, "archived_at": datetime.datetime.fromtimestamp(
                os.path.getmtime(path), tz=datetime.timezone.utc).isoformat(),
            "path": path,
        })
    return versions
