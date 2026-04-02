# ═══════════════════════════════════════════════════════════════════════════════
#  SM-2 ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

import copy
from datetime import datetime, date, timedelta

LEARNING_STEPS  = [1, 10]
GRADUATING_IV   = 1
EASY_IV         = 4
RELEARN_STEPS   = [10]

def _now_iso():
    return datetime.now().isoformat(timespec="seconds")

def _due_in_minutes(mins):
    return (datetime.now() + timedelta(minutes=mins)).isoformat(timespec="seconds")

def _due_in_days(days):
    return (datetime.now() + timedelta(days=days)).isoformat(timespec="seconds")

def sched_init(c):
    c.setdefault("sched_state",   "new")
    c.setdefault("sched_step",    0)
    c.setdefault("sm2_interval",  1)
    c.setdefault("sm2_ease",      2.5)
    c.setdefault("sm2_due",       _now_iso())
    c.setdefault("sm2_repetitions", 0)
    c.setdefault("sm2_last_quality", -1)
    c.setdefault("reviews", 0)
    return c

def sm2_init(c):
    return sched_init(c)

def sched_update(c, quality):
    c = sched_init(c)
    state = c["sched_state"]
    step  = c["sched_step"]
    ef    = c["sm2_ease"]
    iv    = c["sm2_interval"]

    if state == "new":
        state = "learning"
        c["sched_state"] = "learning"

    if state == "review":
        ef = max(1.3, round(
            ef + 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02), 4))

    if quality <= 1:
        steps     = RELEARN_STEPS if state == "review" else LEARNING_STEPS
        new_state = "relearn" if state == "review" else "learning"
        new_step  = 0
        due       = _due_in_minutes(steps[0])

    elif quality == 3:
        if state in ("learning", "relearn"):
            steps     = RELEARN_STEPS if state == "relearn" else LEARNING_STEPS
            new_state = state
            new_step  = step
            if step == 0 and len(steps) > 1:
                hard_mins = (steps[0] + steps[1]) // 2
            else:
                hard_mins = steps[min(step, len(steps) - 1)]
            due = _due_in_minutes(hard_mins)
        else:
            new_state = "review"
            new_step  = 0
            iv        = max(1, round(iv * 1.2))
            due       = _due_in_days(iv)

    elif quality == 5:
        new_state = "review"
        new_step  = 0
        iv        = max(EASY_IV, round(iv * ef)) if state == "review" else EASY_IV
        due       = _due_in_days(iv)

    else:
        if state in ("learning", "relearn"):
            steps     = RELEARN_STEPS if state == "relearn" else LEARNING_STEPS
            next_step = step + 1
            if next_step >= len(steps):
                new_state = "review"
                new_step  = 0
                iv        = GRADUATING_IV
                due       = _due_in_days(iv)
            else:
                new_state = state
                new_step  = next_step
                due       = _due_in_minutes(steps[next_step])
        else:
            new_state = "review"
            new_step  = 0
            iv = (1 if c["sm2_repetitions"] == 0 else
                  6 if c["sm2_repetitions"] == 1 else
                  max(1, round(iv * ef)))
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
        due = datetime.fromisoformat(c.get("sm2_due", ""))
        delta = (due.date() - date.today()).days
        return max(0, delta)
    except Exception:
        return 0

def _fmt_due_interval(c):
    def _preview(quality):
        s = copy.deepcopy(c)
        sched_init(s)
        sched_update(s, quality)
        ns = s["sched_state"]
        if ns in ("learning", "relearn"):
            steps = RELEARN_STEPS if ns == "relearn" else LEARNING_STEPS
            mins  = steps[min(s["sched_step"], len(steps)-1)]
            return f"{mins}m" if mins < 60 else f"{mins//60}h"
        else:
            days = s["sm2_interval"]
            return f"{days}d"
    return {q: _preview(q) for q in [1, 3, 4, 5]}

def sm2_simulate(c, q):
    previews = _fmt_due_interval(c)
    return previews.get(q, "?")

def sm2_badge(c):
    state = c.get("sched_state", "new")
    iv    = c.get("sm2_interval", 1)
    ef    = c.get("sm2_ease", 2.5)
    step  = c.get("sched_step", 0)
    if state == "new":
        return "🆕 New"
    if state in ("learning", "relearn"):
        steps = RELEARN_STEPS if state == "relearn" else LEARNING_STEPS
        mins  = steps[min(step, len(steps)-1)]
        tag   = "🔁 Relearn" if state == "relearn" else "📖 Learning"
        return f"{tag}  step:{step+1}/{len(steps)}  next:{mins}m"
    if is_due_today(c):
        return f"🔴 Review Due  iv:{iv}d  EF:{ef:.2f}"
    return f"✅ {sm2_days_left(c)}d left  iv:{iv}d  EF:{ef:.2f}"
