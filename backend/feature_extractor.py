"""
feature_extractor.py — Extract 8 numeric features from raw JSONB snapshot data

Corrections made vs previous version:
  1.  PAUSE_THRESHOLD          — single constant replaces separate MAX_TYPING_GAP
                                  and IDLE_THRESHOLD (both were 2.0 but defined
                                  independently — risky if one was changed without
                                  the other)

  2.  all_ts sorted by parsed  — sorted(all_ts, key=_parse_ts) instead of plain
      epoch, not string         sorted(all_ts); plain string sort breaks on mixed
                                  timezone offsets e.g. "Z" vs "+05:30"

  3.  window_duration fallback  — condition changed from < 1.0 to <= 0; short but
      condition fixed            legitimate sessions (e.g. 0.3 s burst) were being
                                  silently replaced with 30 s, causing massive
                                  underestimation of typing_speed and scroll_frequency

  4.  keyups sorted by          — keyups list is now sorted by timestamp before use;
      timestamp                   previously assumed JSONB array was already ordered,
                                  which is not guaranteed by Supabase

  5.  key_duration from keyup   — key_duration now uses keyup timestamps (first/last
      timestamps, not all        keyup) to be consistent with typing_speed numerator
      key_events                  (len(keyups)); before, denominator used all
                                  key_events timestamps while numerator counted only
                                  keyups — unit mismatch

  6.  key_duration fallback      — changed from < 1.0 to <= 0 (same reason as #3)
      condition fixed

  7.  mouse_duration fallback    — changed from < 1.0 to <= 0; a fast 0.8 s burst
      condition fixed             of mouse moves was being replaced with full 30 s
                                  window, massively underestimating avg_mouse_speed

  8.  moves sorted by timestamp  — moves list sorted before use; segment-by-segment
                                  distance/speed between moves[i-1] and moves[i]
                                  is wrong if events are out of order

  9.  scrolls sorted by          — same fix applied to scroll event list
      timestamp

  10. scroll_duration fallback   — changed from < 1.0 to <= 0 (same reason as #3)
      condition fixed

  11. idle_ratio total_span      — uses keyups[0]/[-1] after sorting, so span is
      uses sorted keyups          correct; previously could use wrong endpoints if
                                  keyups were unsorted
"""

import math
from datetime import datetime


# ── Single shared pause threshold ─────────────────────────────────────────
# Gaps above this are "idle pauses"; gaps at or below are "typing intervals".
# Defined once so both features always use the same boundary.
PAUSE_THRESHOLD = 2.0   # seconds


def _parse_ts(ts_str: str) -> float:
    """Parse ISO timestamp string to epoch seconds (float)."""
    ts_str = ts_str.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(ts_str)
    except ValueError:
        # Truncate sub-microsecond precision that fromisoformat can't handle
        dt = datetime.fromisoformat(ts_str[:26])
    return dt.timestamp()


def _time_diff(t1: str, t2: str) -> float:
    """Absolute time difference in seconds between two ISO timestamp strings."""
    return abs(_parse_ts(t2) - _parse_ts(t1))


def extract_features(
    key_events:    list | None,
    mouse_events:  list | None,
    scroll_events: list | None,
    summary:       dict | None,
) -> dict | None:
    """
    Extract 8 ML features from a single 30-second snapshot's raw JSONB fields.

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

    # CORRECTION 2: sort by parsed epoch, not by string
    # String sort breaks for mixed timezone offsets ("Z" vs "+05:30")
    all_ts_sorted   = sorted(all_ts, key=_parse_ts)
    window_duration = _time_diff(all_ts_sorted[0], all_ts_sorted[-1])

    # CORRECTION 3: only fall back when duration is truly zero/negative,
    # not for any duration < 1.0 (which silently corrupts short real sessions)
    if window_duration <= 0:
        window_duration = 30.0

    # ── Keyboard features ──────────────────────────────────────────────────

    # CORRECTION 4: sort keyups by timestamp before any use
    keyups = sorted(
        [e for e in key_events if e.get("type") == "keyup"],
        key=lambda e: _parse_ts(e["timestamp"])
    )

    total_keys = len(key_events)
    backspaces = sum(1 for e in key_events if e.get("key") == "Backspace")

    # CORRECTION 5: key_duration uses keyup timestamps so numerator
    # (len(keyups)) and denominator are consistent with each other
    if len(keyups) >= 2:
        key_duration = _time_diff(keyups[0]["timestamp"], keyups[-1]["timestamp"])
    else:
        key_duration = window_duration

    # CORRECTION 6: only fall back on truly zero duration, not < 1.0
    if key_duration <= 0:
        key_duration = window_duration

    typing_speed    = len(keyups) / key_duration
    backspace_ratio = backspaces / total_keys if total_keys > 0 else 0.0

    # Keystroke intervals — gaps <= PAUSE_THRESHOLD are "active typing"
    keystroke_intervals = []
    for i in range(1, len(keyups)):
        ts_prev = keyups[i - 1].get("timestamp")
        ts_curr = keyups[i].get("timestamp")
        if ts_prev and ts_curr:
            dt = _time_diff(ts_prev, ts_curr)
            if 0 < dt <= PAUSE_THRESHOLD:   # CORRECTION 1: shared constant
                keystroke_intervals.append(dt)

    avg_keystroke_interval = (
        sum(keystroke_intervals) / len(keystroke_intervals)
        if keystroke_intervals else 0.0
    )

    # Population std dev in seconds (not variance in s²)
    keystroke_variance = (
        math.sqrt(
            sum((v - avg_keystroke_interval) ** 2 for v in keystroke_intervals)
            / len(keystroke_intervals)
        )
        if keystroke_intervals else 0.0
    )

    # ── Mouse features ─────────────────────────────────────────────────────

    # CORRECTION 8: sort moves by timestamp before segment calculations
    # Accept both "mousemove" (browser/frontend) and "MOVE" (legacy) casing
    moves = sorted(
        [e for e in mouse_events if e.get("type", "").lower() in ("mousemove", "move")],
        key=lambda e: _parse_ts(e["timestamp"])
    )

    # CORRECTION 7: only fall back on truly zero duration, not < 1.0
    if len(moves) >= 2:
        mouse_duration = _time_diff(moves[0]["timestamp"], moves[-1]["timestamp"])
        if mouse_duration <= 0:
            mouse_duration = window_duration
    else:
        mouse_duration = window_duration

    # avg_mouse_speed = total path distance / mouse-only duration
    total_dist = 0.0
    for i in range(1, len(moves)):
        dx = moves[i].get("x", 0) - moves[i - 1].get("x", 0)
        dy = moves[i].get("y", 0) - moves[i - 1].get("y", 0)
        total_dist += math.sqrt(dx * dx + dy * dy)

    avg_mouse_speed = total_dist / mouse_duration if mouse_duration > 0 else 0.0

    # mouse_move_variance = population std dev of per-segment speeds (px/s)
    # Uses mean of per-segment speeds (not avg_mouse_speed) for correct variance
    speeds = []
    for i in range(1, len(moves)):
        dx   = moves[i].get("x", 0) - moves[i - 1].get("x", 0)
        dy   = moves[i].get("y", 0) - moves[i - 1].get("y", 0)
        dist = math.sqrt(dx * dx + dy * dy)
        dt   = _time_diff(moves[i - 1]["timestamp"], moves[i]["timestamp"])
        if dt > 0:
            speeds.append(dist / dt)

    if speeds:
        mean_speed          = sum(speeds) / len(speeds)
        mouse_move_variance = math.sqrt(
            sum((v - mean_speed) ** 2 for v in speeds) / len(speeds)
        )
    else:
        mouse_move_variance = 0.0

    # ── Scroll features ────────────────────────────────────────────────────

    # CORRECTION 9: sort scrolls by timestamp
    # Accept both "scroll" (browser/frontend) and "SCROLL" (legacy) casing
    scrolls = sorted(
        [e for e in scroll_events if e.get("type", "").lower() == "scroll"],
        key=lambda e: _parse_ts(e["timestamp"])
    )

    # CORRECTION 10: only fall back on truly zero duration, not < 1.0
    if len(scrolls) >= 2:
        scroll_duration = _time_diff(scrolls[0]["timestamp"], scrolls[-1]["timestamp"])
        if scroll_duration <= 0:
            scroll_duration = window_duration
    else:
        scroll_duration = window_duration

    scroll_frequency = len(scrolls) / scroll_duration if scroll_duration > 0 else 0.0

    # ── Idle ratio ─────────────────────────────────────────────────────────
    # True keystroke gap ratio: silent time between keyups / total keyup span.
    # Uses PAUSE_THRESHOLD (shared with keystroke intervals) as the idle boundary.

    # CORRECTION 11: keyups already sorted above, so [0] and [-1] are correct
    if len(keyups) >= 2:
        total_span = _time_diff(keyups[0]["timestamp"], keyups[-1]["timestamp"])

        idle_time = 0.0
        for i in range(1, len(keyups)):
            ts_prev = keyups[i - 1].get("timestamp")
            ts_curr = keyups[i].get("timestamp")
            if ts_prev and ts_curr:
                gap = _time_diff(ts_prev, ts_curr)
                if gap > PAUSE_THRESHOLD:   # CORRECTION 1: shared constant
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