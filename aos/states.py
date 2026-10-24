"""Máy trạng thái task (docs/03-trang-thai-task.md): chuyển nào hợp lệ, ai được làm."""

TERMINAL = {"done", "cancelled"}

# (từ, đến) → loại tác nhân được phép
TRANSITIONS = {
    ("backlog", "assigned"): {"human"},
    ("assigned", "backlog"): {"human"},
    ("assigned", "running"): {"worker"},
    ("running", "under_review"): {"worker"},
    ("running", "blocked"): {"worker"},
    ("running", "assigned"): {"worker", "system"},
    ("running", "failed"): {"worker", "system"},
    ("under_review", "done"): {"human"},
    ("under_review", "assigned"): {"human"},
    ("blocked", "assigned"): {"human"},
    ("failed", "assigned"): {"human"},
}
for _s in ("backlog", "assigned", "running", "under_review", "failed", "blocked"):
    TRANSITIONS[(_s, "cancelled")] = {"human"}


class TransitionError(ValueError):
    pass


def actor_kind(actor):
    """'human:van' → 'human'; 'worker:w1' → 'worker'; 'system' → 'system'."""
    return actor.split(":", 1)[0]


def check(current, target, actor):
    allowed = TRANSITIONS.get((current, target))
    if allowed is None:
        raise TransitionError(f"Không chuyển được {current} → {target}")
    if actor_kind(actor) not in allowed:
        raise TransitionError(f"{actor} không được chuyển {current} → {target} (chỉ {', '.join(sorted(allowed))})")
