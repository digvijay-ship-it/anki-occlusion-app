# ═══════════════════════════════════════════════════════════════════════════════
#  FSRS ENGINE — Free Spaced Repetition Scheduler (v4.5 / v5)
#  Machine Learning DSR (Difficulty, Stability, Retrievability) Model
#  Zero external dependencies (pure Python standard library).
# ═══════════════════════════════════════════════════════════════════════════════

import copy
import hashlib
import math
import random
from datetime import datetime, date, timedelta

# Default FSRS-4.5 / 5 parameters trained on millions of Anki reviews
DEFAULT_WEIGHTS = (
    0.40255, 1.18385, 3.173, 15.69105,  # w0-w3: Initial stability for Again, Hard, Good, Easy
    7.1949, 0.5345,                      # w4, w5: Initial difficulty params
    1.4604, 0.0046,                      # w6, w7: Difficulty update & mean reversion
    1.5457, 0.1192, 1.0192,              # w8-w10: Recall stability update params
    1.9395, 0.11, 0.29605, 0.22698,      # w11-w14: Lapse stability update params
    0.2315, 2.9898                       # w15, w16: Hard & Easy bonus multipliers
)

FACTOR = 19.0 / 81.0
DECAY = -0.5
MAX_INTERVAL = 365  # days
DEFAULT_REQUEST_RETENTION = 0.90

LEARNING_STEPS = [1, 10]  # minutes
RELEARN_STEPS = [10]      # minutes

_FUZZ_ID_KEYS = (
    "box_id",
    "group_id",
    "_id",
    "id",
    "card_id",
    "uuid",
    "created",
)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _due_in_minutes(mins: int) -> str:
    return (datetime.now() + timedelta(minutes=mins)).isoformat(timespec="seconds")


def _due_in_days(days: int) -> str:
    due_date = date.today() + timedelta(days=days)
    return datetime.combine(due_date, datetime.min.time()).isoformat(timespec="seconds")


def _stable_seed(*parts) -> int:
    text = "|".join(str(part) for part in parts)
    digest = hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big")


def _fuzz_identity(c) -> str:
    for key in _FUZZ_ID_KEYS:
        val = c.get(key)
        if val not in (None, ""):
            return f"{key}:{val}"
    return ""


def _fuzz_interval(iv: int, seed_val: int = None) -> int:
    if iv <= 2:
        return max(1, iv)

    use_seed = seed_val is not None
    if use_seed:
        state = random.getstate()
        random.seed(seed_val)

    try:
        if iv <= 7:
            fuzz = random.randint(-1, 1)
        elif iv <= 30:
            fuzz = random.randint(-2, 2)
        elif iv <= 90:
            fuzz = random.randint(-3, 4)
        else:
            fuzz = random.randint(-4, 7)
    finally:
        if use_seed:
            random.setstate(state)
    return max(1, min(MAX_INTERVAL, iv + fuzz))


# ─────────────────────────────────────────────────────────────────────────────
#  FSRS MATHEMATICAL FORMULAS
# ─────────────────────────────────────────────────────────────────────────────

def _map_quality_to_grade(quality: int) -> int:
    """Map app quality ratings to FSRS grades (1: Again, 2: Hard, 3: Good, 4: Easy)."""
    if quality <= 1:
        return 1  # Again
    elif quality == 3:
        return 2  # Hard
    elif quality == 4:
        return 3  # Good
    elif quality >= 5:
        return 4  # Easy / Perfect
    return 3


def _initial_stability(grade: int, w=DEFAULT_WEIGHTS) -> float:
    return max(0.1, float(w[grade - 1]))


def _initial_difficulty(grade: int, w=DEFAULT_WEIGHTS) -> float:
    d0 = w[4] - math.exp(w[5] * (grade - 1)) + 1.0
    return min(10.0, max(1.0, float(d0)))


def _next_difficulty(d: float, grade: int, w=DEFAULT_WEIGHTS) -> float:
    d_raw = d - w[6] * (grade - 3)
    d0_good = _initial_difficulty(3, w)
    d_next = w[7] * d0_good + (1.0 - w[7]) * d_raw
    return min(10.0, max(1.0, float(d_next)))


def _retrievability(t_days: float, stability: float) -> float:
    if stability <= 0.0:
        return 0.0
    if t_days <= 0.0:
        return 1.0
    return (1.0 + FACTOR * (t_days / stability)) ** DECAY


def _next_stability_recall(d: float, s: float, r: float, grade: int, w=DEFAULT_WEIGHTS) -> float:
    hard_bonus = w[15] if grade == 2 else 1.0
    easy_bonus = w[16] if grade == 4 else 1.0
    r_clamped = min(1.0, max(0.01, r))
    s_inc = (
        1.0
        + math.exp(w[8])
        * (11.0 - d)
        * (s ** (-w[9]))
        * (math.exp(w[10] * (1.0 - r_clamped)) - 1.0)
        * hard_bonus
        * easy_bonus
    )
    new_s = s * max(1.0, s_inc)
    return max(0.1, float(new_s))


def _next_stability_lapse(d: float, s: float, r: float, w=DEFAULT_WEIGHTS) -> float:
    r_clamped = min(1.0, max(0.01, r))
    new_s = (
        w[11]
        * (d ** (-w[12]))
        * (((s + 1.0) ** w[13]) - 1.0)
        * math.exp(w[14] * (1.0 - r_clamped))
    )
    return max(0.1, min(s, float(new_s)))


def _interval_for_retention(stability: float, request_retention: float = DEFAULT_REQUEST_RETENTION) -> int:
    """Convert stability to optimal calendar interval (days) for requested retention."""
    req_r = min(0.99, max(0.70, float(request_retention)))
    # I = S / FACTOR * (req_r ** (1/DECAY) - 1)
    # With DECAY = -0.5, req_r ** -2 - 1
    mult = (req_r ** -2.0) - 1.0
    raw_iv = (stability / FACTOR) * mult
    iv = max(1, min(MAX_INTERVAL, round(raw_iv)))
    return int(iv)


# ─────────────────────────────────────────────────────────────────────────────
#  INITIALIZATION & STATE PRESERVATION
# ─────────────────────────────────────────────────────────────────────────────

def fsrs_init(c):
    """Ensure FSRS fields are populated, seeding from SM-2 state if present."""
    c.setdefault("sched_state", "new")
    c.setdefault("sched_step", 0)

    # Seed FSRS parameters from existing SM-2 if card was already reviewed
    sm2_iv = c.get("sm2_interval", 1)
    sm2_ease = c.get("sm2_ease", 2.5)
    reviews = c.get("reviews", 0)

    if "fsrs_stability" not in c:
        if reviews > 0 and sm2_iv > 0:
            c["fsrs_stability"] = float(max(1.0, sm2_iv))
        else:
            c["fsrs_stability"] = float(DEFAULT_WEIGHTS[2])  # Good default

    if "fsrs_difficulty" not in c:
        # Convert SM-2 ease (1.3 to 2.5) to FSRS difficulty (1.0 to 10.0)
        # Higher ease = lower difficulty
        ease_ratio = min(1.0, max(0.0, (2.5 - sm2_ease) / (2.5 - 1.3)))
        est_d = 1.0 + ease_ratio * 9.0
        c["fsrs_difficulty"] = float(round(est_d, 2))

    c.setdefault("fsrs_due", c.get("sm2_due", _now_iso()))
    c.setdefault("fsrs_last_review", c.get("reviewed_at", _now_iso()))
    c.setdefault("fsrs_reps", c.get("sm2_repetitions", 0))
    c.setdefault("fsrs_lapses", 0)
    c.setdefault("sm2_last_quality", -1)
    c.setdefault("reviews", reviews)
    return c


# ─────────────────────────────────────────────────────────────────────────────
#  CORE SCHEDULER UPDATE
# ─────────────────────────────────────────────────────────────────────────────

def fsrs_update(c, quality: int, request_retention: float = DEFAULT_REQUEST_RETENTION, weights=DEFAULT_WEIGHTS):
    """
    Update card state according to FSRS DSR model.
    Fully compatible with review_manager, maintaining sm2_due and sm2_interval for UI compatibility.
    """
    c = fsrs_init(c)
    state = c.get("sched_state", "new")
    step = c.get("sched_step", 0)
    s = float(c.get("fsrs_stability", DEFAULT_WEIGHTS[2]))
    d = float(c.get("fsrs_difficulty", 5.0))
    grade = _map_quality_to_grade(quality)

    # Calculate elapsed days since last review
    last_review_str = c.get("fsrs_last_review") or c.get("reviewed_at")
    elapsed_days = 0.0
    if last_review_str:
        try:
            last_dt = datetime.fromisoformat(last_review_str)
            elapsed_days = max(0.0, (datetime.now() - last_dt).total_seconds() / 86400.0)
        except Exception:
            elapsed_days = 0.0

    # Retrievability at review time
    r = _retrievability(elapsed_days, s)

    identity = _fuzz_identity(c)
    seed_val = _stable_seed(identity, c.get("reviews", 0), int(s * 10)) if identity else None

    # Transition new -> learning on first touch
    if state == "new":
        state = "learning"

    # ── INTRADAY / LEARNING STATE ─────────────────────────────────────────────
    if state in ("learning", "relearn"):
        steps = RELEARN_STEPS if state == "relearn" else LEARNING_STEPS

        if quality <= 1:  # Again
            new_state = state
            new_step = 0
            due = _due_in_minutes(steps[0])
            d_next = _initial_difficulty(1, weights) if state == "learning" else _next_difficulty(d, 1, weights)
            s_next = _initial_stability(1, weights)
            iv = 1

        elif quality == 3:  # Hard
            new_state = state
            new_step = step
            hard_mins = (steps[0] + steps[1]) // 2 if step == 0 and len(steps) > 1 else steps[min(step, len(steps) - 1)]
            due = _due_in_minutes(hard_mins)
            d_next = _initial_difficulty(2, weights) if state == "learning" else _next_difficulty(d, 2, weights)
            s_next = _initial_stability(2, weights)
            iv = 1

        elif quality == 5 or quality >= 6:  # Easy / Perfect (Immediate Graduation)
            new_state = "review"
            new_step = 0
            d_next = _initial_difficulty(4, weights)
            s_base = _initial_stability(4, weights)
            s_next = s_base * 1.3 if quality >= 6 else s_base
            iv_raw = _interval_for_retention(s_next, request_retention)
            iv = _fuzz_interval(iv_raw, seed_val)
            due = _due_in_days(iv)

        else:  # Good (quality == 4)
            next_step = step + 1
            if next_step >= len(steps):
                # Graduated to review state!
                new_state = "review"
                new_step = 0
                d_next = _initial_difficulty(3, weights) if c.get("reviews", 0) == 0 else _next_difficulty(d, 3, weights)
                s_next = _initial_stability(3, weights) if c.get("reviews", 0) == 0 else _next_stability_recall(d, s, r, 3, weights)
                iv_raw = _interval_for_retention(s_next, request_retention)
                iv = _fuzz_interval(iv_raw, seed_val)
                due = _due_in_days(iv)
            else:
                new_state = state
                new_step = next_step
                due = _due_in_minutes(steps[next_step])
                d_next = d
                s_next = s
                iv = 1

    # ── REVIEW STATE ──────────────────────────────────────────────────────────
    else:
        if quality <= 1:  # Again (Lapse)
            new_state = "relearn"
            new_step = 0
            due = _due_in_minutes(RELEARN_STEPS[0])
            d_next = _next_difficulty(d, 1, weights)
            s_next = _next_stability_lapse(d, s, r, weights)
            c["fsrs_lapses"] = c.get("fsrs_lapses", 0) + 1
            iv = 1

        else:  # Hard, Good, Easy, Perfect (Recall)
            new_state = "review"
            new_step = 0
            d_next = _next_difficulty(d, grade, weights)
            s_next = _next_stability_recall(d, s, r, grade, weights)

            # Extra multiplier for Perfect rating
            if quality >= 6:
                s_next *= 1.25

            iv_raw = _interval_for_retention(s_next, request_retention)
            iv = _fuzz_interval(iv_raw, seed_val)
            due = _due_in_days(iv)

    now_str = _now_iso()
    c.update({
        "sched_state": new_state,
        "sched_step": new_step,
        "fsrs_stability": float(round(s_next, 4)),
        "fsrs_difficulty": float(round(d_next, 4)),
        "fsrs_due": due,
        "fsrs_last_review": now_str,
        "fsrs_reps": c.get("fsrs_reps", 0) + (1 if quality >= 3 else 0),
        # Keep SM-2 mirrored fields for seamless UI & database compatibility
        "sm2_interval": iv,
        "sm2_due": due,
        "sm2_last_quality": quality,
        "sm2_repetitions": c.get("sm2_repetitions", 0) + (1 if quality >= 3 else 0),
        "reviews": c.get("reviews", 0) + 1,
        "reviewed_at": now_str,
    })
    return c


# ─────────────────────────────────────────────────────────────────────────────
#  PREVIEW SIMULATOR (FSRS Button Labels)
# ─────────────────────────────────────────────────────────────────────────────

def fsrs_fmt_due_interval(c, request_retention: float = DEFAULT_REQUEST_RETENTION):
    """Generate interval labels (e.g. 1m, 10m, 4d, 14d) for each rating button using FSRS."""
    def _preview(quality):
        s = copy.deepcopy(c)
        fsrs_init(s)
        fsrs_update(s, quality, request_retention=request_retention)
        ns = s.get("sched_state", "new")
        if ns in ("learning", "relearn"):
            try:
                due_dt = datetime.fromisoformat(s["fsrs_due"])
                delta = due_dt - datetime.now()
                mins = max(1, round(delta.total_seconds() / 60))
                return f"{mins}m" if mins < 60 else f"{mins // 60}h"
            except Exception:
                steps = RELEARN_STEPS if ns == "relearn" else LEARNING_STEPS
                mins = steps[min(s.get("sched_step", 0), len(steps) - 1)]
                return f"{mins}m" if mins < 60 else f"{mins // 60}h"
        else:
            days = s.get("sm2_interval", 1)
            return f"{days}d"

    previews = {q: _preview(q) for q in [1, 3, 4, 5, 6]}

    # Enforce strictly monotonic display order: Hard <= Good <= Easy <= Perfect for day intervals
    def _parse_days(label):
        return int(label[:-1]) if label.endswith("d") else 0

    if previews[3].endswith("d") and previews[4].endswith("d"):
        h_days = _parse_days(previews[3])
        g_days = _parse_days(previews[4])
        e_days = _parse_days(previews[5])
        p_days = _parse_days(previews[6])

        if h_days > g_days:
            h_days = max(1, g_days - 1)
            previews[3] = f"{h_days}d"
        if e_days <= g_days:
            e_days = g_days + 1
            previews[5] = f"{e_days}d"
        if p_days <= e_days:
            p_days = e_days + 1
            previews[6] = f"{p_days}d"

    return previews


def get_subject_category(deck_name: str) -> str:
    """Classify deck name into 'math', 'english', or 'gk'."""
    if not deck_name:
        return "gk"
    n = deck_name.lower().replace("_", " ")
    math_kw = [
        "math", "calcation", "calculation", "compound interest", "simple interest",
        "number system", "percentage", "ratio", "proportion", "probability",
        "qube", "square", "tabels", "si and ci", "notation", "interst"
    ]
    if any(kw in n for kw in math_kw) or ("time" in n and "distance" in n):
        return "math"
    eng_kw = ["english", "a1", "vocab", "ows", "idiom", "blackbook"]
    if any(kw in n for kw in eng_kw):
        return "english"
    return "gk"
