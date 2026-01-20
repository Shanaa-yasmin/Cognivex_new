console.log("Behavior monitoring initialized");

// ============================
// CONFIGURATION
// ============================
const BATCH_SIZE = 150;
const FLUSH_INTERVAL = 30000; // 30 seconds
const MOUSE_THROTTLE_MS = 120;

// ============================
// STATE
// ============================
let keystrokes = [];
let mouseMoves = [];
let scrolls = [];

let lastKeyTime = null;
let isSending = false;
let lastMouseTime = 0;

// ============================
// SESSION ID (ONE PER LOGIN)
// ============================
let SESSION_ID = localStorage.getItem("SESSION_ID");
if (!SESSION_ID) {
    SESSION_ID = crypto.randomUUID();
    localStorage.setItem("SESSION_ID", SESSION_ID);
}
console.log("Cognivex Session ID:", SESSION_ID);


// ============================
// GET AUTHENTICATED USER
// ============================
async function getUserId() {
    const { data: { session }, error } =
        await window.supabaseClient.auth.getSession();

    if (error || !session) return null;
    return session.user.id;
}

// ============================
// KEYSTROKE CAPTURE (NO RAW KEYS)
// ============================
document.addEventListener("keydown", (e) => {
    const now = Date.now();

    if (lastKeyTime !== null) {
        keystrokes.push({
            key: e.key,
            interval: now - lastKeyTime,
            timestamp: new Date(now).toISOString()
        });
    }

    lastKeyTime = now;
    flushIfNeeded();
});

// ============================
// MOUSE MOVEMENT (THROTTLED)
// ============================
document.addEventListener("mousemove", (e) => {
    const now = Date.now();
    if (now - lastMouseTime < MOUSE_THROTTLE_MS) return;

    mouseMoves.push({
        dx: e.movementX,
        dy: e.movementY,
        timestamp: new Date(now).toISOString()
    });

    lastMouseTime = now;
    flushIfNeeded();
});

// ============================
// SCROLL CAPTURE
// ============================
document.addEventListener("scroll", () => {
    scrolls.push({
        scrollY: window.scrollY,
        timestamp: new Date().toISOString()
    });

    flushIfNeeded();
});

// ============================
// FLUSH CONDITIONS
// ============================
function flushIfNeeded() {
    const total =
        keystrokes.length + mouseMoves.length + scrolls.length;

    if (total >= BATCH_SIZE) {
        flushToSupabase();
    }
}

// Time-based flush
setInterval(() => {
    if (
        keystrokes.length ||
        mouseMoves.length ||
        scrolls.length
    ) {
        flushToSupabase();
    }
}, FLUSH_INTERVAL);

// ============================
// STORE TO SUPABASE (SAFE)
// ============================
async function flushToSupabase() {
    if (isSending) return;

    if (
        !keystrokes.length &&
        !mouseMoves.length &&
        !scrolls.length
    ) return;

    isSending = true;

    // Copy + clear immediately
    const ks = [...keystrokes];
    const mm = [...mouseMoves];
    const sc = [...scrolls];

    keystrokes = [];
    mouseMoves = [];
    scrolls = [];

    try {
        const userId = await getUserId();
        if (!userId) return;

        const payload = {
            user_id: userId,
            session_id: SESSION_ID,
            keystroke_data: ks.length ? ks : null,
            mouse_data: mm.length ? mm : null,
            scroll_data: sc.length ? sc : null,
            metadata: {
                keystroke_count: ks.length,
                mouse_count: mm.length,
                scroll_count: sc.length,
                batch_size: ks.length + mm.length + sc.length,
                user_agent: navigator.userAgent
            }
        };

        const { error } = await window.supabaseClient
            .from("behavior_logs")
            .insert([payload]);

        if (error) throw error;

        console.log("✅ Behavior batch stored");

    } catch (err) {
        console.error("❌ Behavior insert failed:", err.message);

        // Restore data if insert failed
        keystrokes.unshift(...ks);
        mouseMoves.unshift(...mm);
        scrolls.unshift(...sc);

    } finally {
        isSending = false;
    }
}

// ============================
// FLUSH ON TAB HIDE / LOGOUT
// ============================
document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
        flushToSupabase();
    }
});
