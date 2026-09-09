"""Gate: decide whether this GitHub Actions firing is a real snapshot slot.

GitHub cron is UTC-only, fires late under load, and sometimes drops a firing
entirely. So every slot is scheduled twice — once at the EDT offset and once at
the EST offset — and this script decides which firing counts.

The two firings for a slot land about an hour apart, and TOLERANCE_MINUTES is
wide enough that either one can serve it. A marker file under state/ records
that a slot already went out today, so the second firing sends only when the
first was dropped. Those marker commits also keep the repository active, which
stops GitHub disabling the schedule after 60 idle days.

Prints the slot name on stdout and exits 0 when the run should proceed.
"""

import os
import sys
from datetime import datetime, date
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(HERE, "state")

# slot name -> (hour, minute, mode). A firing counts for a slot from its target
# time until TOLERANCE_MINUTES after it.
SLOTS = {
    "open": (9, 30, "full"),
    "midday": (12, 0, "short"),
    "afternoon": (14, 30, "short"),
}
TOLERANCE_MINUTES = 90

# NYSE full-day closures. Extend as needed.
HOLIDAYS = {
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3),
    date(2026, 5, 25), date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7),
    date(2026, 11, 26), date(2026, 12, 25),
    date(2027, 1, 1), date(2027, 1, 18), date(2027, 2, 15), date(2027, 3, 26),
    date(2027, 5, 31), date(2027, 6, 18), date(2027, 7, 5), date(2027, 9, 6),
    date(2027, 11, 25), date(2027, 12, 24),
}


def is_session(day):
    return day.weekday() < 5 and day not in HOLIDAYS


def marker_path(day, slot):
    return os.path.join(STATE_DIR, f"{day:%Y-%m-%d}-{slot}.done")


def already_sent(day, slot):
    return os.path.exists(marker_path(day, slot))


MARKER_KEEP_DAYS = 10


def prune_markers(today):
    """Drop markers older than MARKER_KEEP_DAYS so state/ stays small."""
    if not os.path.isdir(STATE_DIR):
        return
    for name in os.listdir(STATE_DIR):
        if not name.endswith(".done"):
            continue
        try:
            stamp = datetime.strptime(name[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        if (today - stamp).days > MARKER_KEEP_DAYS:
            os.remove(os.path.join(STATE_DIR, name))


def write_marker(day, slot, stamp):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(marker_path(day, slot), "w") as f:
        f.write(f"{stamp}\n")
    prune_markers(day)
    return marker_path(day, slot)


def match_slot(now):
    """The slot whose window contains `now`; ties go to the latest target.

    At 90 minutes the three windows (9:30-11:00, 12:00-13:30, 14:30-16:00) do
    not overlap, so the tie-break never fires today. It is here so that raising
    TOLERANCE_MINUTES later attributes a firing to the most recent slot it could
    belong to, rather than to whichever happens to be first in SLOTS.
    """
    minutes_now = now.hour * 60 + now.minute
    best = (None, None, -1)
    for name, (hour, minute, mode) in SLOTS.items():
        target = hour * 60 + minute
        if target <= minutes_now <= target + TOLERANCE_MINUTES and target > best[2]:
            best = (name, mode, target)
    return best[0], best[1]


def check(now=None, force=False, forced_slot="open"):
    now = now or datetime.now(ET)
    if force:
        slot = forced_slot if forced_slot in SLOTS else "open"
        return True, slot, SLOTS[slot][2], f"forced run ({slot})"
    if not is_session(now.date()):
        why = "weekend" if now.weekday() >= 5 else "market holiday"
        return False, None, None, f"{now:%Y-%m-%d} is a {why}"
    name, mode = match_slot(now)
    if name is None:
        return False, None, None, f"{now:%H:%M} ET matches no snapshot slot"
    if already_sent(now.date(), name):
        return False, None, None, f"{name} slot already sent today; this is the backup firing"
    return True, name, mode, f"{now:%Y-%m-%d %H:%M} ET -> {name} slot ({mode})"


def main(argv):
    force = "--force" in argv
    slot = "open"
    for arg in argv:
        if arg.startswith("--slot=") and arg.split("=", 1)[1]:
            slot = arg.split("=", 1)[1]

    if "--mark" in argv:
        now = datetime.now(ET)
        path = write_marker(now.date(), slot, now.isoformat())
        print(f"wrote {os.path.relpath(path, HERE)}")
        return 0

    ok, name, mode, reason = check(force=force, forced_slot=slot)
    print(reason)
    if ok:
        print(f"SLOT={name}")
        print(f"MODE={mode}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
