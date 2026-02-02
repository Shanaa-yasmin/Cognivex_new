// ============================
// FEATURE EXTRACTION MODULE
// ============================

console.log("📊 Feature extraction module loaded");

let sessionStats = {
    windows: 0,
    sum: {},
};

// Generate unique session ID
function generateSessionId() {
    return 'session_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
}

let currentSessionId = generateSessionId();

function timeDiffSeconds(t1, t2) {
    return Math.abs(new Date(t2) - new Date(t1)) / 1000;
}

// ----------------------------
// MAIN EXTRACTION (30s WINDOW)
// ----------------------------
function extractFeatures(keyEvents, mouseEvents, scrollEvents) {

    if (!keyEvents || !mouseEvents || !scrollEvents) return null;

    const timestamps = [
        ...keyEvents.map(e => e.timestamp),
        ...mouseEvents.map(e => e.timestamp),
        ...scrollEvents.map(e => e.timestamp)
    ];

    if (timestamps.length < 2) return null;

    const windowDuration = timeDiffSeconds(
        timestamps[0],
        timestamps[timestamps.length - 1]
    );

    if (windowDuration === 0) return null;

    // ================= MOUSE =================
    const moves = mouseEvents.filter(e => e.type === "MOVE");
    let speeds = [];

    for (let i = 1; i < moves.length; i++) {
        const dx = moves[i].x - moves[i - 1].x;
        const dy = moves[i].y - moves[i - 1].y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        const dt = timeDiffSeconds(moves[i - 1].timestamp, moves[i].timestamp);
        if (dt > 0) speeds.push(dist / dt);
    }

    const avgMouseSpeed = speeds.length
        ? speeds.reduce((a, b) => a + b, 0) / speeds.length
        : 0;

    const mouseVariance = speeds.length
        ? speeds.reduce((s, v) => s + Math.pow(v - avgMouseSpeed, 2), 0) / speeds.length
        : 0;

    // ================= KEYBOARD =================
    const totalKeys = keyEvents.length;
    const backspaces = keyEvents.filter(e => e.key === "BACKSPACE").length;

    const typingSpeed = totalKeys / windowDuration;
    const backspaceRatio = totalKeys ? backspaces / totalKeys : 0;

    // Keystroke interval (time between keys)
    let keystrokeTimes = [];
    for (let i = 1; i < keyEvents.length; i++) {
        const timeDiff = timeDiffSeconds(keyEvents[i - 1].timestamp, keyEvents[i].timestamp);
        if (timeDiff > 0) keystrokeTimes.push(timeDiff);
    }

    const avgKeystrokeInterval = keystrokeTimes.length > 0
        ? keystrokeTimes.reduce((a, b) => a + b, 0) / keystrokeTimes.length
        : 0;

    const keystrokeVariance = keystrokeTimes.length > 0
        ? keystrokeTimes.reduce((s, v) => s + Math.pow(v - avgKeystrokeInterval, 2), 0) / keystrokeTimes.length
        : 0;

    // ================= SCROLL =================
    const scrolls = scrollEvents.filter(e => e.type === "SCROLL");
    const scrollFrequency = scrolls.length / windowDuration;

    // ================= IDLE =================
    const activeEvents = keyEvents.length + mouseEvents.length + scrolls.length;
    const idleRatio = 1 - Math.min(1, activeEvents / (windowDuration * 5));

    // Window features for ML training
    const windowFeatures = {
        typing_speed: typingSpeed,
        backspace_ratio: backspaceRatio,
        avg_keystroke_interval: avgKeystrokeInterval,
        keystroke_variance: keystrokeVariance,
        avg_mouse_speed: avgMouseSpeed,
        mouse_move_variance: mouseVariance,
        scroll_frequency: scrollFrequency,
        idle_ratio: idleRatio
    };

    accumulateSession(windowFeatures);
    return windowFeatures;
}

// ----------------------------
// SESSION ACCUMULATION
// ----------------------------
function accumulateSession(features) {
    sessionStats.windows++;

    for (let key in features) {
        if (!sessionStats.sum[key]) {
            sessionStats.sum[key] = 0;
        }
        sessionStats.sum[key] += features[key];
    }
}

// ----------------------------
// CALL THIS AT SESSION END
// ----------------------------
function getSessionSummary() {
    if (sessionStats.windows === 0) return null;

    let summary = {};

    for (let key in sessionStats.sum) {
        summary[key] = parseFloat(
            (sessionStats.sum[key] / sessionStats.windows).toFixed(4)
        );
    }

    summary.session_id = currentSessionId;
    summary.total_windows = sessionStats.windows;
    summary.generated_at = new Date().toISOString();

    console.log("✅ Final Session Summary:", summary);
    return summary;
}

// ----------------------------
// RESET SESSION
// ----------------------------
function resetSession() {
    sessionStats = {
        windows: 0,
        sum: {},
    };
    currentSessionId = generateSessionId();
    console.log("🔄 Session stats reset, new session ID:", currentSessionId);
}

// ----------------------------
// EXPORTS
// ----------------------------
window.extractBehaviorFeatures = extractFeatures;
window.getSessionSummary = getSessionSummary;
window.resetSession = resetSession;

console.log("✅ Feature extraction module ready");