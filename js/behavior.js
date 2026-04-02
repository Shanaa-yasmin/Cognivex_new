console.log("Behavior monitoring initialized (v2 - backend-driven)");

// ============================
// CONFIGURATION
// ============================
const BACKEND_URL = "http://localhost:8000";
const FLUSH_INTERVAL = 30000;    // 30 seconds
const MOUSE_THROTTLE_MS = 200;

// ============================
// STATE
// ============================
let keyEvents = [];
let mouseEvents = [];
let scrollEvents = [];
let userId = null;
let isSending = false;
let lastMouseTime = 0;
let monitoringActive = true;
let otpPending = false;
let sessionEndSent = false;
let snapshotsSentCount = 0;

// ============================
// SESSION ID (FRESH EVERY LOGIN)
// ============================
let SESSION_ID = crypto.randomUUID();
localStorage.setItem("SESSION_ID", SESSION_ID);
console.log("Cognivex Session ID:", SESSION_ID);

// ============================
// INITIALIZATION
// ============================
async function initBehaviorTracking() {
    console.log("Waiting for Supabase and Auth...");
    const maxAttempts = 50;
    let attempts = 0;

    return new Promise((resolve) => {
        const checkReady = setInterval(async () => {
            attempts++;
            if (window.supabaseClient && window.supabaseHelper) {
                clearInterval(checkReady);
                userId = await window.supabaseHelper.getUserId();
                if (userId) {
                    console.log("User ID obtained:", userId);
                    setupEventListeners();
                    startSnapshotTimer();
                    resolve(true);
                } else {
                    console.error("Failed to get user ID");
                    resolve(false);
                }
            } else if (attempts >= maxAttempts) {
                clearInterval(checkReady);
                console.error("Supabase/Auth failed to initialize");
                resolve(false);
            }
        }, 100);
    });
}

// ============================
// EVENT LISTENERS
// ============================
function setupEventListeners() {
    console.log("Setting up event listeners...");

    document.addEventListener("keydown", (e) => {
        if (!monitoringActive) return;
        keyEvents.push({
            type: "keydown",
            key: e.key,
            timestamp: new Date().toISOString()
        });
    });

    document.addEventListener("keyup", (e) => {
        if (!monitoringActive) return;
        keyEvents.push({
            type: "keyup",
            key: e.key,
            timestamp: new Date().toISOString()
        });
    });

    document.addEventListener("mousemove", (e) => {
        if (!monitoringActive) return;
        const now = Date.now();
        if (now - lastMouseTime < MOUSE_THROTTLE_MS) return;
        mouseEvents.push({
            type: "MOVE", x: e.clientX, y: e.clientY,
            timestamp: new Date().toISOString()
        });
        lastMouseTime = now;
    }, { passive: true });

    document.addEventListener("click", (e) => {
        if (!monitoringActive) return;
        mouseEvents.push({
            type: "CLICK", x: e.clientX, y: e.clientY,
            element: e.target.tagName, timestamp: new Date().toISOString()
        });
    });

    window.addEventListener("scroll", () => {
        if (!monitoringActive) return;
        scrollEvents.push({
            type: "SCROLL",
            scrollY: window.scrollY, scrollX: window.scrollX,
            windowHeight: window.innerHeight,
            pageHeight: document.documentElement.scrollHeight,
            scrollPercent: Math.round(
                (window.scrollY / Math.max(1, document.documentElement.scrollHeight - window.innerHeight)) * 100
            ),
            timestamp: new Date().toISOString()
        });
    }, { passive: true });

    const textarea = document.getElementById('researchNotes');
    if (textarea) {
        textarea.addEventListener('focus', () => {
            scrollEvents.push({ type: "FOCUS", element: "research_notes", timestamp: new Date().toISOString() });
        });
        textarea.addEventListener('blur', () => {
            scrollEvents.push({ type: "BLUR", element: "research_notes", timestamp: new Date().toISOString() });
        });
    }

    console.log("Event listeners setup complete");
}

// ============================
// 30-SECOND SNAPSHOT TIMER
// ============================
let snapshotTimer = null;

function startSnapshotTimer() {
    snapshotTimer = setInterval(() => {
        if (otpPending) return;
        const total = keyEvents.length + mouseEvents.length + scrollEvents.length;
        if (total > 0) {
            console.log("30s snapshot triggered (" + total + " events)");
            sendSnapshotToBackend();
        }
    }, FLUSH_INTERVAL);
}

// ============================
// SEND SNAPSHOT TO BACKEND
// ============================
async function sendSnapshotToBackend() {
    if (isSending || !monitoringActive) return;

    const total = keyEvents.length + mouseEvents.length + scrollEvents.length;
    if (total === 0) return;

    isSending = true;

    const ke = [...keyEvents];
    const me = [...mouseEvents];
    const se = [...scrollEvents];
    keyEvents = [];
    mouseEvents = [];
    scrollEvents = [];

    try {
        if (!userId) {
            userId = await window.supabaseHelper.getUserId();
        }
        if (!userId) {
            keyEvents.unshift(...ke);
            mouseEvents.unshift(...me);
            scrollEvents.unshift(...se);
            return;
        }

        const payload = {
            user_id: userId,
            session_id: SESSION_ID,
            key_events: ke.length > 0 ? ke : [],
            mouse_events: me.length > 0 ? me : [],
            scroll_events: se.length > 0 ? se : [],
            summary: {
                total_keys_pressed: ke.length,
                total_mouse_movements: me.filter(e => e.type === 'MOVE').length,
                total_clicks: me.filter(e => e.type === 'CLICK').length,
                total_scroll_events: se.filter(e => e.type === 'SCROLL').length,
                total_events: ke.length + me.length + se.length,
                timestamp: new Date().toISOString()
            }
        };

        console.log("Sending snapshot to backend...", payload.summary);

        const response = await fetch(BACKEND_URL + "/session/snapshot", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });

        if (!response.ok) {
            throw new Error("Backend returned " + response.status);
        }

        const result = await response.json();
        console.log("Backend response:", result);
        snapshotsSentCount++;

        handleRiskResponse(result);

    } catch (err) {
        console.error("Snapshot send failed:", err.message);
        keyEvents.unshift(...ke);
        mouseEvents.unshift(...me);
        scrollEvents.unshift(...se);
    } finally {
        isSending = false;
    }
}

// ============================
// RISK RESPONSE HANDLER
// ============================
function handleRiskResponse(result) {
    const statusDot = document.querySelector('.status-dot');
    const statusText = document.querySelector('.status-indicator span:last-child');

    switch (result.status) {
        case "OK":
        case "COLLECTING_DATA":
            if (statusDot) statusDot.style.background = '#10b981';
            if (statusText) statusText.textContent = 'Session Active - Behavioral Monitoring Enabled';
            break;

        case "OTP_REQUIRED":
            console.warn("MEDIUM risk detected - OTP required");
            if (statusDot) statusDot.style.background = '#f59e0b';
            if (statusText) statusText.textContent = 'Identity Verification Required';
            showOTPDialog(result.session_id);
            break;

        // ── Grace period: shown on status bar + logged to console (inspect page) ──
        case "GRACE_PERIOD":
            if (statusDot) statusDot.style.background = '#3b82f6';  // blue
            if (statusText) statusText.textContent =
                `Grace Period Active — ${result.remaining_minutes} min remaining (scoring paused)`;
            console.log(
                `%c[GRACE PERIOD] Active — ${result.remaining_minutes} min remaining. Scoring is paused.`,
                'background: #1e3a5f; color: #60a5fa; font-weight: bold; padding: 2px 6px; border-radius: 3px;'
            );
            break;

        case "SESSION_TERMINATED":
            console.error("HIGH risk - session terminated");
            if (statusDot) statusDot.style.background = '#ef4444';
            if (statusText) statusText.textContent = 'Session Terminated - Anomaly Detected';
            forceLogout("Behavioral anomaly detected. Session terminated.");
            break;
    }
}

// ============================
// OTP DIALOG
// ============================
function showOTPDialog(sessionId) {
    otpPending = true;

    let modal = document.getElementById('otpModal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'otpModal';
        modal.innerHTML = '<div class="otp-overlay">' +
            '<div class="otp-dialog">' +
            '<h3>Identity Verification</h3>' +
            '<p>Unusual behavior detected. Please enter the verification code to continue.</p>' +
            '<p class="otp-hint">Code: <strong>2323</strong></p>' +
            '<input type="text" id="otpInput" maxlength="4" placeholder="Enter code" autocomplete="off" />' +
            '<div class="otp-buttons">' +
            '<button id="otpSubmitBtn" class="btn btn-primary">Verify</button>' +
            '</div>' +
            '<p id="otpError" class="otp-error"></p>' +
            '<p class="otp-timer">Expires in <span id="otpCountdown">15</span>s</p>' +
            '</div></div>';
        document.body.appendChild(modal);
    }

    modal.style.display = 'block';
    document.getElementById('otpInput').value = '';
    document.getElementById('otpError').textContent = '';

    var seconds = 15;
    var countdownEl = document.getElementById('otpCountdown');
    var countdown = setInterval(function() {
        seconds--;
        if (countdownEl) countdownEl.textContent = seconds;
        if (seconds <= 0) {
            clearInterval(countdown);
            closeOTPDialog();
            forceLogout("Verification timed out. Session terminated.");
        }
    }, 1000);

    var submitBtn = document.getElementById('otpSubmitBtn');
    var inputEl = document.getElementById('otpInput');

    var doSubmit = async function() {
        var code = inputEl.value.trim();
        if (!code) return;

        submitBtn.disabled = true;
        submitBtn.textContent = 'Verifying...';

        try {
            var resp = await fetch(BACKEND_URL + "/verify-otp", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    user_id: userId,
                    session_id: sessionId,
                    otp_code: code,
                }),
            });

            var result = await resp.json();
            console.log("OTP verification result:", result);

            if (result.status === "OTP_VERIFIED") {
                clearInterval(countdown);
                closeOTPDialog();

                // ── Show grace period started immediately after OTP success ──
                var dot = document.querySelector('.status-dot');
                var txt = document.querySelector('.status-indicator span:last-child');
                if (dot) dot.style.background = '#3b82f6';
                if (txt) txt.textContent =
                    `Grace Period Started — ${result.grace_period_minutes} min (scoring paused)`;
                console.log(
                    `%c[GRACE PERIOD STARTED] Identity verified. Scoring paused for ${result.grace_period_minutes} minutes.`,
                    'background: #1e3a5f; color: #60a5fa; font-weight: bold; padding: 2px 6px; border-radius: 3px;'
                );

            } else {
                clearInterval(countdown);
                closeOTPDialog();
                forceLogout("Verification failed. Session terminated.");
            }
        } catch (err) {
            console.error("OTP verification error:", err);
            document.getElementById('otpError').textContent = 'Verification failed. Try again.';
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Verify';
        }
    };

    submitBtn.onclick = doSubmit;
    inputEl.onkeydown = function(e) { if (e.key === 'Enter') doSubmit(); };
}

function closeOTPDialog() {
    var modal = document.getElementById('otpModal');
    if (modal) modal.style.display = 'none';
    otpPending = false;
}

// ============================
// FORCE LOGOUT
// ============================
function forceLogout(reason) {
    monitoringActive = false;
    if (snapshotTimer) clearInterval(snapshotTimer);
    alert(reason);
    localStorage.removeItem("SESSION_ID");
    if (window.authHandler) {
        window.authHandler.logout();
    } else {
        window.location.href = 'index.html';
    }
}

// ============================
// SESSION END (called on logout)
// ============================
async function sendSessionEnd() {
    if (sessionEndSent) {
        console.log("Session-end already sent, skipping.");
        return { status: "ALREADY_SENT" };
    }
    sessionEndSent = true;
    monitoringActive = false;
    if (snapshotTimer) clearInterval(snapshotTimer);
    console.log("Sending session-end to backend for session:", SESSION_ID);

    try {
        await sendSnapshotToBackend();
    } catch (e) {
        console.warn("Final snapshot flush failed:", e.message);
    }

    if (snapshotsSentCount === 0) {
        console.log("No snapshots sent this session, skipping session-end.");
        localStorage.removeItem("SESSION_ID");
        return { status: "NO_DATA" };
    }

    if (!userId) {
        try { userId = await window.supabaseHelper.getUserId(); } catch(e) {}
    }
    if (!userId) {
        console.error("Cannot send session-end: No user ID");
        return { status: "NO_USER" };
    }

    var endPayload = JSON.stringify({ user_id: userId, session_id: SESSION_ID });

    try {
        var controller = new AbortController();
        var timeoutId = setTimeout(function() { controller.abort(); }, 8000);

        var resp = await fetch(BACKEND_URL + "/session/end", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: endPayload,
            signal: controller.signal,
        });
        clearTimeout(timeoutId);

        var result = await resp.json();
        console.log("Session-end response:", result);
        localStorage.removeItem("SESSION_ID");
        return result;
    } catch (err) {
        console.error("Session-end fetch failed, using beacon fallback:", err.message);
        navigator.sendBeacon(
            BACKEND_URL + "/session/end",
            new Blob([endPayload], { type: "application/json" })
        );
        localStorage.removeItem("SESSION_ID");
        return { status: "BEACON_SENT" };
    }
}

// Global exports
window.sendSessionEnd = sendSessionEnd;
window.flushBehaviorData = sendSnapshotToBackend;

// Flush on tab hide
document.addEventListener("visibilitychange", function() {
    if (document.visibilityState === "hidden") {
        sendSnapshotToBackend();
    }
});

// Session-end beacon on page unload
window.addEventListener("beforeunload", function() {
    if (userId && SESSION_ID && !sessionEndSent && snapshotsSentCount > 0) {
        sessionEndSent = true;
        var payload = JSON.stringify({ user_id: userId, session_id: SESSION_ID });
        navigator.sendBeacon(BACKEND_URL + "/session/end", new Blob([payload], { type: "application/json" }));
    }
});

// Start monitoring
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() { initBehaviorTracking(); });
} else {
    initBehaviorTracking();
}