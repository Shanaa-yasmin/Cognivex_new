console.log("🎯 Behavior monitoring initialized");

// ============================
// CONFIGURATION
// ============================
const BATCH_SIZE = 100;           // Flush when batch reaches 100 events
const FLUSH_INTERVAL = 30000;     // Flush every 30 seconds
const MOUSE_THROTTLE_MS = 200;    // Throttle mouse events to 200ms

// ============================
// STATE - Simple arrays to store events
// ============================
let keyEvents = [];               // Store actual key names pressed
let mouseEvents = [];             // Store mouse movements and clicks
let scrollEvents = [];            // Store scroll positions
let userId = null;
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
// INITIALIZATION
// ============================
async function initBehaviorTracking() {
    console.log("⏳ Waiting for Supabase and Auth...");
    
    const maxAttempts = 50;
    let attempts = 0;

    return new Promise((resolve) => {
        const checkReady = setInterval(async () => {
            attempts++;
            
            if (window.supabaseClient && window.supabaseHelper && window.extractBehaviorFeatures) {
                clearInterval(checkReady);
                console.log("✅ Supabase ready, getting user ID...");
                
                userId = await window.supabaseHelper.getUserId();
                
                if (userId) {
                    console.log("✅ User ID obtained:", userId);
                    setupEventListeners();
                    resolve(true);
                } else {
                    console.error("❌ Failed to get user ID");
                    resolve(false);
                }
            } else if (attempts >= maxAttempts) {
                clearInterval(checkReady);
                console.error("❌ Supabase/Auth/Features failed to initialize");
                resolve(false);
            }
        }, 100);
    });
}

// ============================
// EVENT LISTENERS SETUP
// ============================
function setupEventListeners() {
    console.log("📡 Setting up event listeners...");

    // ============================
    // KEYSTROKE CAPTURE - Store actual key names
    // ============================
    document.addEventListener("keydown", (e) => {
        let keyName = e.key;
        
        // Convert common keys to readable names
        if (keyName === ' ') keyName = 'SPACE';
        if (keyName === 'Enter') keyName = 'ENTER';
        if (keyName === 'Backspace') keyName = 'BACKSPACE';
        if (keyName === 'Tab') keyName = 'TAB';
        if (keyName === 'Shift') keyName = 'SHIFT';
        if (keyName === 'Control') keyName = 'CTRL';
        if (keyName === 'Alt') keyName = 'ALT';
        if (keyName === 'Escape') keyName = 'ESC';
        if (keyName === 'ArrowUp') keyName = 'ARROW_UP';
        if (keyName === 'ArrowDown') keyName = 'ARROW_DOWN';
        if (keyName === 'ArrowLeft') keyName = 'ARROW_LEFT';
        if (keyName === 'ArrowRight') keyName = 'ARROW_RIGHT';

        // Store the key event
        keyEvents.push({
            key: keyName,                    // The actual key name (a, b, c, ENTER, SPACE, etc)
            timestamp: new Date().toISOString()
        });

        console.log("⌨️ Key pressed:", keyName);
        flushIfNeeded();
    });

    // ============================
    // MOUSE MOVEMENT (THROTTLED) - Store position changes
    // ============================
    document.addEventListener("mousemove", (e) => {
        const now = Date.now();
        if (now - lastMouseTime < MOUSE_THROTTLE_MS) return;

        mouseEvents.push({
            type: "MOVE",                    // Type of mouse event
            x: e.clientX,                    // Horizontal position on screen
            y: e.clientY,                    // Vertical position on screen
            timestamp: new Date().toISOString()
        });

        lastMouseTime = now;
        console.log("🖱️ Mouse moved to:", e.clientX, e.clientY);
        flushIfNeeded();
    }, { passive: true });

    // ============================
    // MOUSE CLICK CAPTURE - Store click locations
    // ============================
    document.addEventListener("click", (e) => {
        mouseEvents.push({
            type: "CLICK",                   // Type of mouse event
            x: e.clientX,                    // Click X position
            y: e.clientY,                    // Click Y position
            element: e.target.tagName,       // What element was clicked (BUTTON, INPUT, etc)
            timestamp: new Date().toISOString()
        });

        console.log("🖱️ Clicked:", e.target.tagName, "at", e.clientX, e.clientY);
        flushIfNeeded();
    });

    // ============================
    // SCROLL CAPTURE - Store scroll position
    // ============================
    window.addEventListener("scroll", () => {
        scrollEvents.push({
            type: "SCROLL",                  // Type of scroll
            scrollY: window.scrollY,         // How far down the page (pixels)
            scrollX: window.scrollX,         // How far right the page (pixels)
            windowHeight: window.innerHeight,// Height of visible window
            pageHeight: document.documentElement.scrollHeight,  // Total page height
            scrollPercent: Math.round((window.scrollY / (document.documentElement.scrollHeight - window.innerHeight)) * 100),  // Percentage scrolled
            timestamp: new Date().toISOString()
        });

        console.log("📜 Scroll position Y:", window.scrollY, "Percent:", Math.round((window.scrollY / (document.documentElement.scrollHeight - window.innerHeight)) * 100) + "%");
        flushIfNeeded();
    }, { passive: true });

    // ============================
    // TEXTAREA FOCUS/BLUR - Track user focus
    // ============================
    const textarea = document.getElementById('researchNotes');
    if (textarea) {
        textarea.addEventListener('focus', () => {
            scrollEvents.push({
                type: "FOCUS",                // User focused on textarea
                element: "research_notes",
                timestamp: new Date().toISOString()
            });
            console.log("📝 Research notes textarea FOCUSED");
        });

        textarea.addEventListener('blur', () => {
            scrollEvents.push({
                type: "BLUR",                 // User left textarea
                element: "research_notes",
                timestamp: new Date().toISOString()
            });
            console.log("📝 Research notes textarea BLURRED");
        });
    }

    console.log("✅ Event listeners setup complete");
}

// ============================
// FLUSH CONDITIONS
// ============================
function flushIfNeeded() {
    const total = keyEvents.length + mouseEvents.length + scrollEvents.length;

    if (total >= BATCH_SIZE) {
        console.log(`📤 Batch size (${total}) reached, flushing...`);
        flushToSupabase();
    }
}

// Time-based flush every 30 seconds
setInterval(() => {
    const total = keyEvents.length + mouseEvents.length + scrollEvents.length;
    
    if (total > 0) {
        console.log(`⏱️ Time-based flush triggered (${total} events)`);
        flushToSupabase();
    }
}, FLUSH_INTERVAL);

// ============================
// STORE RAW BEHAVIOR DATA TO SUPABASE
// ============================
async function flushToSupabase() {
    if (isSending) {
        console.log("⏳ Already sending, skipping flush...");
        return;
    }

    const total = keyEvents.length + mouseEvents.length + scrollEvents.length;
    
    if (total === 0) {
        console.log("ℹ️ No events to flush");
        return;
    }

    isSending = true;

    // Copy arrays immediately
    const ke = [...keyEvents];
    const me = [...mouseEvents];
    const se = [...scrollEvents];

    try {
        // Get fresh user ID if not set
        if (!userId) {
            userId = await window.supabaseHelper.getUserId();
        }

        if (!userId) {
            console.error("❌ Cannot flush: No user ID available");
            // Restore data
            keyEvents.unshift(...ke);
            mouseEvents.unshift(...me);
            scrollEvents.unshift(...se);
            return;
        }

        // ============================
        // STEP 1: EXTRACT WINDOW FEATURES (for accumulation only)
        // ============================
        const windowFeatures = window.extractBehaviorFeatures(ke, me, se);
        console.log("📊 Window features extracted:", windowFeatures);

        if (!windowFeatures) {
            console.warn("⚠️ Feature extraction returned null, skipping this flush");
            keyEvents.unshift(...ke);
            mouseEvents.unshift(...me);
            scrollEvents.unshift(...se);
            return;
        }

        // ============================
        // STEP 2: STORE RAW BEHAVIOR DATA ONLY (NOT individual features)
        // ============================
        const payload = {
            user_id: userId,
            key_events: ke.length > 0 ? ke : null,         // Only include if we have data
            mouse_events: me.length > 0 ? me : null,       // Only include if we have data
            scroll_events: se.length > 0 ? se : null,      // Only include if we have data
            summary: {
                total_keys_pressed: ke.length,
                total_mouse_movements: me.filter(e => e.type === 'MOVE').length,
                total_clicks: me.filter(e => e.type === 'CLICK').length,
                total_scroll_events: se.filter(e => e.type === 'SCROLL').length,
                total_events: ke.length + me.length + se.length,
                timestamp: new Date().toISOString()
            }
        };

        console.log("📤 Sending behavior data to Supabase:", payload.summary);

        const result = await window.supabaseHelper.insertBehaviorData(payload);

        if (!result.success) {
            throw new Error(result.error?.message || "Failed to insert behavior data");
        }

        console.log("✅ Behavior batch stored successfully");

        // ============================
        // STEP 3: CLEAR ARRAYS ONLY IF ALL SUCCESSFUL
        // ============================
        keyEvents = [];
        mouseEvents = [];
        scrollEvents = [];

    } catch (err) {
        console.error("❌ Behavior insert failed:", err.message);

        // Restore data if insert failed (will retry next time)
        keyEvents.unshift(...ke);
        mouseEvents.unshift(...me);
        scrollEvents.unshift(...se);

    } finally {
        isSending = false;
    }
}

// Make flush function globally accessible
window.flushBehaviorData = flushToSupabase;

// ============================
// SAVE SESSION FEATURES ON LOGOUT
// ============================
async function saveSessionFeatures() {
    console.log("💾 Saving session features on logout...");

    // First, flush any remaining behavior data
    await flushToSupabase();

    // Get the session summary
    const sessionSummary = window.getSessionSummary();

    if (!sessionSummary) {
        console.warn("⚠️ No session summary to save");
        return;
    }

    if (!userId) {
        userId = await window.supabaseHelper.getUserId();
    }

    if (!userId) {
        console.error("❌ Cannot save features: No user ID");
        return;
    }

    try {
        // Store aggregated session features to behavior_features table
        const featureResult = await window.supabaseHelper.insertBehaviorFeatures(userId, sessionSummary);

        if (!featureResult.success) {
            throw new Error(featureResult.error?.message || "Failed to insert features");
        }

        console.log("✅ Session features stored successfully:", sessionSummary);

        // Reset session for next login
        window.resetSession();

    } catch (err) {
        console.error("❌ Session features insert failed:", err.message);
    }
}

// Make save function globally accessible
window.saveSessionFeatures = saveSessionFeatures;

// ============================
// FLUSH ON TAB HIDE / PAGE UNLOAD
// ============================
document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
        console.log("👁️ Tab hidden, flushing behavior data...");
        flushToSupabase();
    }
});

// Flush on page unload (but NOT features - that's done on logout)
window.addEventListener("beforeunload", () => {
    console.log("📄 Page unloading, flushing behavior data...");
    flushToSupabase();
});

// ============================
// START MONITORING
// ============================
document.addEventListener("DOMContentLoaded", () => {
    console.log("📄 DOM loaded, starting behavior monitoring...");
    initBehaviorTracking();
});

// Fallback if DOM is already loaded
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        initBehaviorTracking();
    });
} else {
    initBehaviorTracking();
}