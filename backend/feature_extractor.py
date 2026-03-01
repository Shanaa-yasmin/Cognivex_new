"""
feature_extractor.py — Extract 8 numeric features from raw JSONB data
"""

import math
from datetime import datetime


def _parse_ts(ts_str: str) -> float:
    """Parse ISO timestamp string to epoch seconds."""
    # Handle both 'Z' suffix and '+00:00' offset
    ts_str = ts_str.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(ts_str)
    except ValueError:
        # Fallback: strip trailing timezone info and parse
        dt = datetime.fromisoformat(ts_str[:26])
    return dt.timestamp()


def _time_diff(t1: str, t2: str) -> float:
    """Absolute time difference in seconds between two ISO timestamps."""
    return abs(_parse_ts(t2) - _parse_ts(t1))


def extract_features(key_events: list | None,
                     mouse_events: list | None,
                     scroll_events: list | None,
                     summary: dict | None) -> dict | None:
    """
    Extract the 8 ML features from a single snapshot's raw JSONB fields.

    Returns dict with keys:
        typing_speed, backspace_ratio, avg_keystroke_interval,
        keystroke_variance, avg_mouse_speed, mouse_move_variance,
        scroll_frequency, idle_ratio
    or None if insufficient data.
    """
    key_events = key_events or []
    mouse_events = mouse_events or []
    scroll_events = scroll_events or []

    # Collect all timestamps to determine window duration
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

    all_ts_sorted = sorted(all_ts)
    window_duration = _time_diff(all_ts_sorted[0], all_ts_sorted[-1])
    if window_duration == 0:
        return None

    # ── Keyboard features ──
    total_keys = len(key_events)
    backspaces = sum(1 for e in key_events if e.get("key") == "BACKSPACE")
    typing_speed = total_keys / window_duration
    backspace_ratio = backspaces / total_keys if total_keys > 0 else 0.0

    keystroke_intervals = []
    for i in range(1, len(key_events)):
        ts_prev = key_events[i - 1].get("timestamp")
        ts_curr = key_events[i].get("timestamp")
        if ts_prev and ts_curr:
            dt = _time_diff(ts_prev, ts_curr)
            if dt > 0:
                keystroke_intervals.append(dt)

    avg_keystroke_interval = (
        sum(keystroke_intervals) / len(keystroke_intervals)
        if keystroke_intervals else 0.0
    )
    keystroke_variance = (
        sum((v - avg_keystroke_interval) ** 2 for v in keystroke_intervals) / len(keystroke_intervals)
        if keystroke_intervals else 0.0
    )

    # ── Mouse features ──
    moves = [e for e in mouse_events if e.get("type") == "MOVE"]
    speeds = []
    for i in range(1, len(moves)):
        dx = moves[i].get("x", 0) - moves[i - 1].get("x", 0)
        dy = moves[i].get("y", 0) - moves[i - 1].get("y", 0)
        dist = math.sqrt(dx * dx + dy * dy)
        dt = _time_diff(moves[i - 1]["timestamp"], moves[i]["timestamp"])
        if dt > 0:
            speeds.append(dist / dt)

    avg_mouse_speed = sum(speeds) / len(speeds) if speeds else 0.0
    mouse_move_variance = (
        sum((v - avg_mouse_speed) ** 2 for v in speeds) / len(speeds)
        if speeds else 0.0
    )

    # ── Scroll features ──
    scrolls = [e for e in scroll_events if e.get("type") == "SCROLL"]
    scroll_frequency = len(scrolls) / window_duration

    # ── Idle ratio ──
    active_events = len(key_events) + len(mouse_events) + len(scrolls)
    idle_ratio = 1.0 - min(1.0, active_events / (window_duration * 5))

    return {
        "typing_speed": round(typing_speed, 4),
        "backspace_ratio": round(backspace_ratio, 4),
        "avg_keystroke_interval": round(avg_keystroke_interval, 4),
        "keystroke_variance": round(keystroke_variance, 4),
        "avg_mouse_speed": round(avg_mouse_speed, 4),
        "mouse_move_variance": round(mouse_move_variance, 4),
        "scroll_frequency": round(scroll_frequency, 4),
        "idle_ratio": round(idle_ratio, 4),
    }


def aggregate_features(feature_list: list[dict]) -> dict | None:
    """
    Average multiple feature dicts into one aggregated feature dict.
    Used at session end to combine LOW-risk snapshot features.
    """
    if not feature_list:
        return None

    keys = [
        "typing_speed", "backspace_ratio", "avg_keystroke_interval",
        "keystroke_variance", "avg_mouse_speed", "mouse_move_variance",
        "scroll_frequency", "idle_ratio",
    ]

    aggregated = {}
    n = len(feature_list)
    for k in keys:
        total = sum(f.get(k, 0.0) for f in feature_list)
        aggregated[k] = round(total / n, 4)

    aggregated["total_windows"] = n
    return aggregated
