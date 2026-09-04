"""Gate: decide whether this GitHub Actions firing is a real snapshot slot.

GitHub cron is UTC-only and can fire several minutes late, so the workflow
schedules every slot twice (EDT offset and EST offset) and this script keeps
whichever firing actually lands near a target ET time today.

Prints the slot name on stdout and exits 0 when the run should proceed.
"""

import sys
from datetime import datetime, date
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# slot name -> (hour, minute, mode). Runs are accepted from the target time
# until TOLERANCE_MINUTES after it.
SLOTS = {
    "open": (9, 30, "full"),
    "midday": (12, 0, "short"),
    "afternoon": (14, 30, "short"),
}
TOLERANCE_MINUTES = 45

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


def match_slot(now):
    minutes_now = now.hour * 60 + now.minute
    for name, (hour, minute, mode) in SLOTS.items():
        target = hour * 60 + minute
        if target <= minutes_now <= target + TOLERANCE_MINUTES:
            return name, mode
    return None, None


def check(now=None, force=False, forced_slot="open"):
    now = now or datetime.now(ET)
    if force:
        return True, forced_slot, SLOTS[forced_slot][2], "forced run"
    if not is_session(now.date()):
        why = "weekend" if now.weekday() >= 5 else "market holiday"
        return False, None, None, f"{now:%Y-%m-%d} is a {why}"
    name, mode = match_slot(now)
    if name is None:
        return False, None, None, f"{now:%H:%M} ET matches no snapshot slot"
    return True, name, mode, f"{now:%Y-%m-%d %H:%M} ET -> {name} slot ({mode})"


if __name__ == "__main__":
    force = "--force" in sys.argv
    slot = "open"
    for arg in sys.argv[1:]:
        if arg.startswith("--slot="):
            slot = arg.split("=", 1)[1]
    ok, name, mode, reason = check(force=force, forced_slot=slot)
    print(reason)
    if ok:
        print(f"SLOT={name}")
        print(f"MODE={mode}")
    sys.exit(0 if ok else 1)
