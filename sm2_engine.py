# ═══════════════════════════════════════════════════════════════════════════════
#  SM-2 ENGINE — Fixed & Extended
#  Fixes:
#    1. Hard (q=3) EF penalty now correctly applies -0.15 in review state
#    2. Hard (q=3) interval uses 1.2x multiplier (was correct, now explicit)
#    3. Good (q=4) in review now uses standard SM-2 EF (no change = correct)
#    4. Easy (q=5) in review now applies +0.15 EF bonus
#    5. Interval fuzzing added for review intervals > 2 days
#    6. Max interval cap added (default 365 days)
# ═══════════════════════════════════════════════════════════════════════════════

import copy
import random
from datetime import datetime, date, timedelta

LEARNING_STEPS  = [1, 10]       # minutes
GRADUATING_IV   = 1             # days
EASY_IV         = 4             # days
RELEARN_STEPS   = [10]          # minutes
MAX_INTERVAL    = 365           # days — cap to avoid 10-year intervals

def _now_iso():
    return datetime.now().isoformat(timespec="seconds")

def _due_in_minutes(mins):
    return (datetime.now() + timedelta(minutes=mins)).isoformat(timespec="seconds")

def _due_in_days(days):
    return (datetime.now() + timedelta(days=days)).isoformat(timespec="seconds")

# ─────────────────────────────────────────────────────────────────────────────
#  INTERVAL FUZZING
#  Prevents card pile-ups by adding a small random offset to review intervals.
#  Anki-style: fuzz range grows with interval size.
# ─────────────────────────────────────────────────────────────────────────────
def _fuzz_interval(iv: int) -> int:
    """Add a small random fuzz to intervals > 2 days to avoid pile-ups."""
    if iv <= 2:
        return iv  # No fuzz for very short intervals
    if iv <= 7:
        fuzz = random.randint(-1, 1)        # ±1 day
    elif iv <= 30:
        fuzz = random.randint(-2, 2)        # ±2 days
    elif iv <= 90:
        fuzz = random.randint(-3, 4)        # -3 to +4 days
    else:
        fuzz = random.randint(-4, 7)        # -4 to +7 days
    return max(1, iv + fuzz)

# ─────────────────────────────────────────────────────────────────────────────
#  EF UPDATES — Discrete Anki-style penalties per quality rating
#  Replaces the continuous formula for review cards.
#  Again (q=1): -0.20  Hard (q=3): -0.15  Good (q=4): 0.00  Easy (q=5): +0.15
# ─────────────────────────────────────────────────────────────────────────────
EF_DELTA = {
    1: -0.20,   # Again
    3: -0.15,   # Hard
    4:  0.00,   # Good
    5: +0.15,   # Easy
}

def _update_ef(ef: float, quality: int) -> float:
    """Apply discrete EF delta. Clamp between 1.3 and 2.5 (Anki max is 2.5)."""
    delta = EF_DELTA.get(quality, 0.0)
    return round(max(1.3, min(2.5, ef + delta)), 4)

# ─────────────────────────────────────────────────────────────────────────────
#  SCHEDULER INIT
# ─────────────────────────────────────────────────────────────────────────────
def sched_init(c):
    c.setdefault("sched_state",        "new")
    c.setdefault("sched_step",         0)
    c.setdefault("sm2_interval",       1)
    c.setdefault("sm2_ease",           2.5)
    c.setdefault("sm2_due",            _now_iso())
    c.setdefault("sm2_repetitions",    0)
    c.setdefault("sm2_last_quality",   -1)
    c.setdefault("reviews",            0)
    return c

def sm2_init(c):
    return sched_init(c)

# ─────────────────────────────────────────────────────────────────────────────
#  CORE SCHEDULER UPDATE
# ─────────────────────────────────────────────────────────────────────────────
def sched_update(c, quality):
    c     = sched_init(c)
    state = c["sched_state"]
    step  = c["sched_step"]
    ef    = c["sm2_ease"]
    iv    = c["sm2_interval"]

    # Transition new → learning on first touch
    if state == "new":
        state = "learning"

    # ── AGAIN (quality <= 1) ──────────────────────────────────────────────────
    if quality <= 1:
        if state == "review":
            ef = _update_ef(ef, 1)          # Penalize EF on lapse
        steps     = RELEARN_STEPS if state == "review" else LEARNING_STEPS
        new_state = "relearn"    if state == "review" else "learning"
        new_step  = 0
        due       = _due_in_minutes(steps[0])

    # ── HARD (quality == 3) ───────────────────────────────────────────────────
    elif quality == 3:
        if state in ("learning", "relearn"):
            steps = RELEARN_STEPS if state == "relearn" else LEARNING_STEPS
            new_state = state
            new_step  = step
            # Hard = midpoint between current step and next step
            if step == 0 and len(steps) > 1:
                hard_mins = (steps[0] + steps[1]) // 2   # (1+10)//2 = 5 min
            else:
                hard_mins = steps[min(step, len(steps) - 1)]
            due = _due_in_minutes(hard_mins)
        else:
            # Review state: Hard → 1.2x interval, EF -0.15
            ef        = _update_ef(ef, 3)
            new_state = "review"
            new_step  = 0
            iv        = min(MAX_INTERVAL, max(1, round(iv * 1.2)))
            iv        = _fuzz_interval(iv)
            due       = _due_in_days(iv)

    # ── EASY (quality == 5) ───────────────────────────────────────────────────
    elif quality == 5:
        if state == "review":
            ef = _update_ef(ef, 5)          # Reward EF on easy
        new_state = "review"
        new_step  = 0
        if state == "review":
            iv = min(MAX_INTERVAL, max(EASY_IV, round(iv * ef)))
        else:
            iv = EASY_IV
        iv  = _fuzz_interval(iv)
        due = _due_in_days(iv)

    # ── GOOD (quality == 4) ───────────────────────────────────────────────────
    else:
        if state in ("learning", "relearn"):
            steps     = RELEARN_STEPS if state == "relearn" else LEARNING_STEPS
            next_step = step + 1
            if next_step >= len(steps):
                # Graduated!
                new_state = "review"
                new_step  = 0
                iv        = GRADUATING_IV
                due       = _due_in_days(iv)
            else:
                new_state = state
                new_step  = next_step
                due       = _due_in_minutes(steps[next_step])
        else:
            # Review state: Good → standard SM-2, EF unchanged
            ef        = _update_ef(ef, 4)   # delta = 0, but keeps clamp logic
            new_state = "review"
            new_step  = 0
            iv = (1 if c["sm2_repetitions"] == 0 else
                  6 if c["sm2_repetitions"] == 1 else
                  min(MAX_INTERVAL, max(1, round(iv * ef))))
            iv  = _fuzz_interval(iv)
            due = _due_in_days(iv)

    c.update({
        "sched_state":       new_state,
        "sched_step":        new_step,
        "sm2_interval":      iv,
        "sm2_ease":          ef,
        "sm2_due":           due,
        "sm2_last_quality":  quality,
        "sm2_repetitions":   c["sm2_repetitions"] + (1 if quality >= 3 else 0),
        "reviews":           c.get("reviews", 0) + 1,
    })
    return c

def sm2_update(c, quality):
    return sched_update(c, quality)

# ─────────────────────────────────────────────────────────────────────────────
#  DUE CHECKS
# ─────────────────────────────────────────────────────────────────────────────
def is_due_now(c):
    sched_init(c)
    if c.get("sm2_last_quality", -1) == -1:
        return True
    due_str = c.get("sm2_due", "")
    if not due_str:
        return True
    try:
        return datetime.fromisoformat(due_str) <= datetime.now()
    except Exception:
        return True

def is_due_today(c):
    sched_init(c)
    state = c.get("sched_state", "new")
    if state in ("new", "learning", "relearn"):
        return is_due_now(c)
    due_str = c.get("sm2_due", "")
    if not due_str:
        return True
    try:
        due_date = datetime.fromisoformat(due_str).date()
        return due_date <= date.today()
    except Exception:
        return True

def sm2_is_due(c):
    return is_due_today(c)

def sm2_days_left(c):
    try:
        due   = datetime.fromisoformat(c.get("sm2_due", ""))
        delta = (due.date() - date.today()).days
        return max(0, delta)
    except Exception:
        return 0

# ─────────────────────────────────────────────────────────────────────────────
#  PREVIEW SIMULATOR  (what interval will each button show?)
# ─────────────────────────────────────────────────────────────────────────────
def _fmt_due_interval(c):
    def _preview(quality):
        s  = copy.deepcopy(c)
        sched_init(s)
        sched_update(s, quality)
        ns = s["sched_state"]
        if ns in ("learning", "relearn"):
            # ✅ FIX: Read actual due datetime, not step index
            # Step index was always 0 for Hard, giving wrong 1m label
            try:
                due_dt  = datetime.fromisoformat(s["sm2_due"])
                delta   = due_dt - datetime.now()
                mins    = max(1, round(delta.total_seconds() / 60))
                return f"{mins}m" if mins < 60 else f"{mins // 60}h"
            except Exception:
                steps = RELEARN_STEPS if ns == "relearn" else LEARNING_STEPS
                mins  = steps[min(s["sched_step"], len(steps) - 1)]
                return f"{mins}m" if mins < 60 else f"{mins // 60}h"
        else:
            days = s["sm2_interval"]
            return f"{days}d"
    return {q: _preview(q) for q in [1, 3, 4, 5]}

def sm2_simulate(c, q):
    previews = _fmt_due_interval(c)
    return previews.get(q, "?")

# ─────────────────────────────────────────────────────────────────────────────
#  BADGE
# ─────────────────────────────────────────────────────────────────────────────
def sm2_badge(c):
    state = c.get("sched_state", "new")
    iv    = c.get("sm2_interval", 1)
    ef    = c.get("sm2_ease",    2.5)
    step  = c.get("sched_step",    0)
    if state == "new":
        return "🆕 New"
    if state in ("learning", "relearn"):
        steps = RELEARN_STEPS if state == "relearn" else LEARNING_STEPS
        mins  = steps[min(step, len(steps) - 1)]
        tag   = "🔁 Relearn" if state == "relearn" else "📖 Learning"
        return f"{tag}  step:{step + 1}/{len(steps)}  next:{mins}m"
    if is_due_today(c):
        return f"🔴 Review Due  iv:{iv}d  EF:{ef:.2f}"
    return f"✅ {sm2_days_left(c)}d left  iv:{iv}d  EF:{ef:.2f}"


# ─────────────────────────────────────────────────────────────────────────────
#  QUICK SMOKE TEST
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=== Learning Phase ===")
    card = {}
    sched_init(card)

    for label, q in [("Again", 1), ("Hard", 3), ("Good", 4), ("Easy", 5)]:
        c = copy.deepcopy(card)
        sched_update(c, q)
        print(f"  {label:5s} (q={q}) → state:{c['sched_state']:8s}  due:{c['sm2_due'][11:16]}  ef:{c['sm2_ease']:.2f}")

    print("\n=== Review Phase ===")
    review_card = {
        "sched_state": "review", "sched_step": 0,
        "sm2_interval": 10, "sm2_ease": 2.5,
        "sm2_due": _now_iso(), "sm2_repetitions": 5,
        "sm2_last_quality": 4, "reviews": 5
    }
    for label, q in [("Again", 1), ("Hard", 3), ("Good", 4), ("Easy", 5)]:
        c = copy.deepcopy(review_card)
        sched_update(c, q)
        print(f"  {label:5s} (q={q}) → iv:{c['sm2_interval']:3d}d  ef:{c['sm2_ease']:.2f}  due:{c['sm2_due'][:10]}")