"""
feature_extractor.py — Extract 8 numeric features from raw JSONB data

Changes from original:
  1. backspace_ratio      — key name fixed "BACKSPACE" → "Backspace" (JS standard)
  2. keystroke_variance   — changed from population variance to std dev (seconds),
                            matching friend's np.std(intervals)/1000
  3. avg_mouse_speed      — duration now uses mouse-only timestamps (not all events)
  4. mouse_move_variance  — changed from population variance to std dev (px/s),
                            removed speed < 5000 cap, fixed mean to use per-segment speeds
  5. scroll_frequency     — duration now uses scroll-only timestamps (not all events)
  6. idle_ratio           — complete rewrite: now measures true keystroke gap ratio
                            (silent time between keyups / total keyup span) instead of
                            the old event-rate proxy

Bug fixes vs previous version:
  A. typing_speed         — fixed indentation: was always 0.0 when key_duration >= 1.0
  B. key_duration         — added else branch so it's always defined
  C. mouse_move_variance  — fixed mean: now uses mean of per-segment speeds, not
                            avg_mouse_speed (total dist / time)
"""

import math
from datetime import datetime


def _parse_ts(ts_str: str) -> float:
    """Parse ISO timestamp string to epoch seconds."""
    ts_str = ts_str.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(ts_str)
    except ValueError:
        dt = datetime.fromisoformat(ts_str[:26])
    return dt.timestamp()


def _time_diff(t1: str, t2: str) -> float:
    """Absolute time difference in seconds between two ISO timestamps."""
    return abs(_parse_ts(t2) - _parse_ts(t1))


def extract_features(
    key_events:    list | None,
    mouse_events:  list | None,
    scroll_events: list | None,
    summary:       dict | None,
) -> dict | None:
    """
    Extract the 8 ML features from a single snapshot's raw JSONB fields.

    Returns a dict with keys:
        typing_speed, backspace_ratio, avg_keystroke_interval,
        keystroke_variance, avg_mouse_speed, mouse_move_variance,
        scroll_frequency, idle_ratio
    or None if the snapshot has insufficient data.
    """
    key_events    = key_events    or []
    mouse_events  = mouse_events  or []
    scroll_events = scroll_events or []

    # ── Window duration (all events combined) ─────────────────────────────
    all_ts = []
    for e in key_events:
        if "timestamp" in e:
            all_ts.append(e["timestamp"])
    for e in mouse_events:
        if "timestamp" in e:
            all_ts.append(e["timestamp"])
    for e in scroll_events:
        if "timestamp" in e:
            all_ts.append(e["timestamp"])

    if len(all_ts) < 2:
        return None

    all_ts_sorted   = sorted(all_ts)
    window_duration = _time_diff(all_ts_sorted[0], all_ts_sorted[-1])

    if window_duration < 1.0:
        window_duration = 30.0

    # ── Keyboard features ──────────────────────────────────────────────────

    # Use keyup events only for speed and intervals (consistent with friend's code)
    keyups     = [e for e in key_events if e.get("type") == "keyup"]
    total_keys = len(key_events)

    # FIX 1: JS KeyboardEvent.key standard is "Backspace", not "BACKSPACE"
    backspaces = sum(1 for e in key_events if e.get("key") == "Backspace")

    # FIX A: added else branch so key_duration is always defined
    if len(key_events) >= 2:
        key_duration = _time_diff(key_events[0]["timestamp"], key_events[-1]["timestamp"])
    else:
        key_duration = window_duration

    if key_duration < 1.0:
        key_duration = window_duration

    # FIX B: typing_speed moved outside if/else so it's always calculated
    typing_speed = len(keyups) / key_duration

    backspace_ratio = backspaces / total_keys if total_keys > 0 else 0.0

    MAX_TYPING_GAP = 2.0  # seconds

    keystroke_intervals = []
    for i in range(1, len(keyups)):
        ts_prev = keyups[i - 1].get("timestamp")
        ts_curr = keyups[i].get("timestamp")
        if ts_prev and ts_curr:
            dt = _time_diff(ts_prev, ts_curr)
            if 0 < dt <= MAX_TYPING_GAP:
                keystroke_intervals.append(dt)

    avg_keystroke_interval = (
        sum(keystroke_intervals) / len(keystroke_intervals)
        if keystroke_intervals else 0.0
    )

    # FIX 2: std dev in seconds, not population variance in seconds^2
    keystroke_variance = (
        math.sqrt(
            sum((v - avg_keystroke_interval) ** 2 for v in keystroke_intervals)
            / len(keystroke_intervals)
        )
        if keystroke_intervals else 0.0
    )

    # ── Mouse features ─────────────────────────────────────────────────────

    moves = [e for e in mouse_events if e.get("type") == "MOVE"]

    # FIX 3: use mouse-only duration for avg_mouse_speed
    if len(moves) >= 2:
        mouse_duration = _time_diff(
            moves[0]["timestamp"], moves[-1]["timestamp"]
        )
        if mouse_duration < 1.0:
            mouse_duration = window_duration
    else:
        mouse_duration = window_duration

    total_dist = 0.0
    for i in range(1, len(moves)):
        dx = moves[i].get("x", 0) - moves[i - 1].get("x", 0)
        dy = moves[i].get("y", 0) - moves[i - 1].get("y", 0)
        total_dist += math.sqrt(dx * dx + dy * dy)

    avg_mouse_speed = total_dist / mouse_duration if mouse_duration > 0 else 0.0

    # FIX 4 & C: std dev (px/s) using mean of per-segment speeds (not avg_mouse_speed)
    speeds = []
    for i in range(1, len(moves)):
        dx = moves[i].get("x", 0) - moves[i - 1].get("x", 0)
        dy = moves[i].get("y", 0) - moves[i - 1].get("y", 0)
        dist = math.sqrt(dx * dx + dy * dy)
        dt   = _time_diff(moves[i - 1]["timestamp"], moves[i]["timestamp"])
        if dt > 0:
            speeds.append(dist / dt)

    if speeds:
        mean_speed = sum(speeds) / len(speeds)
        mouse_move_variance = math.sqrt(
            sum((v - mean_speed) ** 2 for v in speeds) / len(speeds)
        )
    else:
        mouse_move_variance = 0.0

    # ── Scroll features ────────────────────────────────────────────────────

    scrolls = [e for e in scroll_events if e.get("type") == "SCROLL"]

    # FIX 5: use scroll-only duration for scroll_frequency
    if len(scrolls) >= 2:
        scroll_duration = _time_diff(
            scrolls[0]["timestamp"], scrolls[-1]["timestamp"]
        )
        if scroll_duration < 1.0:
            scroll_duration = window_duration
    else:
        scroll_duration = window_duration

    scroll_frequency = len(scrolls) / scroll_duration if scroll_duration > 0 else 0.0

    # ── Idle ratio ─────────────────────────────────────────────────────────

    # FIX 6: true keystroke gap ratio
    IDLE_THRESHOLD = 2.0  # seconds — gaps longer than this count as idle

    if len(keyups) >= 2:
        total_span = _time_diff(keyups[0]["timestamp"], keyups[-1]["timestamp"])

        idle_time = 0.0
        for i in range(1, len(keyups)):
            ts_prev = keyups[i - 1].get("timestamp")
            ts_curr = keyups[i].get("timestamp")
            if ts_prev and ts_curr:
                gap = _time_diff(ts_prev, ts_curr)
                if gap > IDLE_THRESHOLD:
                    idle_time += gap

        idle_ratio = idle_time / total_span if total_span > 0 else 0.0
        idle_ratio = max(0.0, min(1.0, idle_ratio))
    else:
        idle_ratio = 0.0

    return {
        "typing_speed":           round(typing_speed,            4),
        "backspace_ratio":        round(backspace_ratio,         4),
        "avg_keystroke_interval": round(avg_keystroke_interval,  4),
        "keystroke_variance":     round(keystroke_variance,      4),
        "avg_mouse_speed":        round(avg_mouse_speed,         4),
        "mouse_move_variance":    round(mouse_move_variance,     4),
        "scroll_frequency":       round(scroll_frequency,        4),
        "idle_ratio":             round(idle_ratio,              4),
    }


def aggregate_features(feature_list: list[dict]) -> dict | None:
    """
    Average multiple feature dicts into one aggregated feature dict.
    Used at session end to combine all LOW-risk snapshot features into
    the single row stored to behavior_features.
    """
    if not feature_list:
        return None

    keys = [
        "typing_speed", "backspace_ratio", "avg_keystroke_interval",
        "keystroke_variance", "avg_mouse_speed", "mouse_move_variance",
        "scroll_frequency", "idle_ratio",
    ]

    n = len(feature_list)
    aggregated = {
        k: round(sum(f.get(k, 0.0) for f in feature_list) / n, 4)
        for k in keys
    }
    aggregated["total_windows"] = n
    return aggregated