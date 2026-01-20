import numpy as np
from supabase import create_client
from dotenv import load_dotenv
import os
from datetime import datetime
from collections import defaultdict

# ============================
# CONFIG
# ============================
ENROLLMENT_SESSIONS = 10
IDLE_THRESHOLD = 2  # seconds

# ============================
# LOAD ENV
# ============================
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ============================
# FETCH RAW LOGS
# ============================
def fetch_behavior_logs(user_id):
    response = (
        supabase
        .table("behavior_logs")
        .select("*")
        .eq("user_id", user_id)
        .order("timestamp", desc=False)
        .execute()
    )
    return response.data

# ============================
# FEATURE EXTRACTION
# ============================
def extract_features(session_logs):
    keystrokes, mouse, scrolls = [], [], []

    for row in session_logs:
        keystrokes += row.get("keystroke_data") or []
        mouse += row.get("mouse_data") or []
        scrolls += row.get("scroll_data") or []

    def ts(t):
        return datetime.fromisoformat(t.replace("Z", ""))

    key_times = [ts(k["timestamp"]) for k in keystrokes]
    mouse_times = [ts(m["timestamp"]) for m in mouse]
    scroll_times = [ts(s["timestamp"]) for s in scrolls]

    all_times = sorted(key_times + mouse_times + scroll_times)
    if len(all_times) < 2:
        return None

    session_duration = (all_times[-1] - all_times[0]).total_seconds()

    # ---------- Keyboard ----------
    key_intervals = [
        (key_times[i] - key_times[i - 1]).total_seconds()
        for i in range(1, len(key_times))
    ]

    avg_key_interval = np.mean(key_intervals) if key_intervals else 0
    std_key_interval = np.std(key_intervals) if key_intervals else 0
    key_rate = len(key_times) / session_duration

    # ---------- Mouse ----------
    speeds, idle_mouse = [], 0
    for i in range(1, len(mouse)):
        dx, dy = mouse[i]["dx"], mouse[i]["dy"]
        dt = (ts(mouse[i]["timestamp"]) - ts(mouse[i - 1]["timestamp"])).total_seconds()

        if dt > 0:
            speeds.append(np.sqrt(dx**2 + dy**2) / dt)
        if dt > IDLE_THRESHOLD:
            idle_mouse += dt

    avg_mouse_speed = np.mean(speeds) if speeds else 0
    std_mouse_speed = np.std(speeds) if speeds else 0
    mouse_idle_ratio = idle_mouse / session_duration

    # ---------- Scroll ----------
    scroll_distances = [
        abs(scrolls[i]["scrollY"] - scrolls[i - 1]["scrollY"])
        for i in range(1, len(scrolls))
    ]

    avg_scroll_distance = np.mean(scroll_distances) if scroll_distances else 0
    scroll_frequency = len(scrolls) / session_duration

    # ---------- Interaction ----------
    interaction_rate = (
        len(key_times) + len(mouse_times) + len(scroll_times)
    ) / session_duration

    # ---------- Global Idle ----------
    idle_time = 0
    for i in range(1, len(all_times)):
        gap = (all_times[i] - all_times[i - 1]).total_seconds()
        if gap > IDLE_THRESHOLD:
            idle_time += gap

    idle_time_ratio = idle_time / session_duration

    return {
        "avg_key_interval": avg_key_interval,
        "std_key_interval": std_key_interval,
        "key_rate": key_rate,
        "avg_mouse_speed": avg_mouse_speed,
        "std_mouse_speed": std_mouse_speed,
        "mouse_idle_ratio": mouse_idle_ratio,
        "avg_scroll_distance": avg_scroll_distance,
        "scroll_frequency": scroll_frequency,
        "interaction_rate": interaction_rate,
        "idle_time_ratio": idle_time_ratio,
        "session_duration": session_duration
    }

# ============================
# STORE FEATURES
# ============================
def store_features(user_id, session_id, features):
    supabase.table("behavior_features").insert({
        "user_id": user_id,
        "session_id": session_id,
        **features
    }).execute()

# ============================
# ENROLLMENT PIPELINE
# ============================
def enrollment_pipeline(user_id):
    logs = fetch_behavior_logs(user_id)

    sessions = defaultdict(list)
    for row in logs:
        sessions[row["session_id"]].append(row)

    stored = 0
    for session_id, session_logs in sessions.items():
        if stored >= ENROLLMENT_SESSIONS:
            break

        features = extract_features(session_logs)
        if features:
            store_features(user_id, session_id, features)
            stored += 1
            print(f"✅ Stored features for session {stored}")

    print("🎯 Enrollment completed")

# ============================
# RUN
# ============================
if __name__ == "__main__":
    USER_ID = "PUT_USER_ID_HERE"
    enrollment_pipeline(USER_ID)
