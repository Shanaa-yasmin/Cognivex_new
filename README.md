<div align="center">

# 🔐 Cognivex
### Continuous User Authentication using Behavioral Biometrics

*Authenticate users continuously — not just at login — using how they type, move, and scroll.*

[Live Demo](#-live-demo) · [How It Works](#-how-it-works) · [Features](#-features) · [Architecture](#-architecture) · [Installation](#-installation) · [API Reference](#-api-reference)

</div>

---

## 🌐 Live Demo

| Service | URL |
|---|---|
| **Frontend** | [cognivex-main.vercel.app](https://cognivex-main.vercel.app) |
| **Backend API** | [cognivex-oul6.onrender.com](https://cognivex-oul6.onrender.com/health) |
| **API Docs** | [cognivex-oul6.onrender.com/docs](https://cognivex-oul6.onrender.com/docs) |

---

## 💡 How It Works

Traditional authentication asks *"who are you?"* once at login. Cognivex asks it continuously — every 30 seconds — by analyzing the unique patterns in how a person interacts with a device.

```
Browser                      Backend                       Database
  │                             │                              │
  │── keydown/keyup/mousemove ──▶│                              │
  │── scroll events (30s) ──────▶│                              │
  │                             │── extract 8 features ───────▶│
  │                             │── IsolationForest score      │
  │                             │── adaptive threshold check   │
  │◀── LOW: continue ───────────│                              │
  │◀── MEDIUM: OTP challenge ───│── issue OTP ────────────────▶│
  │◀── HIGH: session terminated─│                              │
```

The system learns what *your* behavior looks like over 15+ sessions, then flags deviations — someone else using your account, or a bot, will score as an anomaly.

---

## ✨ Features

**Behavioral Monitoring**
- Continuous 30-second snapshot windows — not a one-time check
- Captures keystroke dynamics (timing, rhythm, backspace patterns)
- Captures mouse dynamics (speed, trajectory variance, click patterns)
- Captures scroll behavior (frequency and rhythm)
- All feature math happens server-side — clients cannot spoof scores

**Adaptive Risk Engine**
- IsolationForest anomaly detection — unsupervised, no labeled attack data needed
- Per-user adaptive thresholds computed from each user's own behavior distribution
- Progressive model training: collects 15 sessions, then retrains every 10 sessions
- Sliding window of 50 most recent sessions keeps the model current

**Three-Tier Risk Response**

| Risk Level | Score Range | Action |
|---|---|---|
| 🟢 LOW | Above MEDIUM threshold | Session continues normally |
| 🟡 MEDIUM | Between thresholds | OTP email challenge issued |
| 🔴 HIGH | Below HIGH threshold | Session terminated immediately |

**Step-up Authentication**
- OTP challenge delivered via email on MEDIUM risk
- 5-minute OTP expiry with countdown timer in UI
- 10-minute grace period after successful OTP — no rescoring during this window
- Wrong or expired OTP → immediate session termination

**Session Lifecycle**
- `sendBeacon` fallback ensures session-end is always reported even on hard tab close
- Idempotent session-end: duplicate calls are safely ignored
- Sliding window cleanup keeps behavior_logs under 500 rows per user

---

## 🏗 Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     FRONTEND (Vercel)                    │
│                                                          │
│  index.html / dashboard.html / signup.html               │
│         │                                                │
│  behavior.js  ←── collects raw events                   │
│         │         sends snapshots every 30s              │
│         │         handles OTP dialog + force logout      │
└─────────┼───────────────────────────────────────────────┘
          │  POST /session/snapshot
          │  POST /session/end
          │  POST /verify-otp
          ▼
┌─────────────────────────────────────────────────────────┐
│                    BACKEND (Render)                      │
│                                                          │
│  main.py              ← FastAPI routes + CORS            │
│  session_controller.py ← snapshot pipeline + grace      │
│  feature_extractor.py  ← 8 numeric features from events │
│  model_engine.py       ← IsolationForest + thresholds   │
│  otp_controller.py     ← issue + verify OTP via email   │
│  supabase_client.py    ← all DB operations              │
└─────────┼───────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────┐
│                   DATABASE (Supabase)                    │
│                                                          │
│  behavior_logs      ← raw 30s snapshots + risk labels   │
│  behavior_features  ← aggregated session features       │
│  model_metadata     ← serialized model + thresholds     │
│  otp_challenges     ← OTP codes + expiry + status       │
└─────────────────────────────────────────────────────────┘
```

### The 8 Extracted Features

| Feature | What it measures |
|---|---|
| `typing_speed` | Keystrokes per second |
| `backspace_ratio` | Error correction rate |
| `avg_keystroke_interval` | Mean gap between keystrokes (≤2s) |
| `keystroke_variance` | Rhythm consistency (std dev of intervals) |
| `avg_mouse_speed` | Total path distance / mouse-active duration |
| `mouse_move_variance` | Smoothness vs jerkiness of movement |
| `scroll_frequency` | Scroll events per second |
| `idle_ratio` | Fraction of typing span spent idle (>2s gaps) |

### Model Training Strategy

```
Sessions 1–14   → COLLECTING_DATA (no model yet)
Session 15      → First train on all 15 rows
Sessions 16–49  → Retrain on all rows (growing window)
Sessions 50+    → Retrain on latest 50 (sliding window)
Retrain trigger → Every 10 new sessions
Recency weight  → Most recent 20% of rows get 2× weight
```

---

## 🚀 Installation

### Prerequisites

- Python 3.11+
- Supabase project with service role key
- Resend account (free) for OTP email delivery

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/cognivex.git
cd cognivex
```

### 2. Backend setup

```bash
cd backend
python -m venv .venv

# Windows
.\.venv\Scripts\Activate.ps1

# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

Create `backend/.env`:

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your_service_role_key
RESEND_API_KEY=re_your_resend_api_key
```

### 3. Supabase tables

Run these in your Supabase SQL editor:

```sql
-- Raw behavioral snapshots
create table behavior_logs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users,
  session_id text,
  key_events jsonb,
  mouse_events jsonb,
  scroll_events jsonb,
  summary jsonb,
  risk_level text,
  model_version int,
  created_at timestamptz default now()
);

-- Aggregated session features for training
create table behavior_features (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users,
  session_id text,
  typing_speed float, backspace_ratio float,
  avg_keystroke_interval float, keystroke_variance float,
  avg_mouse_speed float, mouse_move_variance float,
  scroll_frequency float, idle_ratio float,
  total_windows int,
  generated_at timestamptz,
  created_at timestamptz default now()
);

-- Trained model + adaptive thresholds (one row per user)
create table model_metadata (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users,
  model_version int,
  model_binary text,
  feature_columns jsonb,
  total_sessions int,
  last_trained_count int,
  medium_threshold float,
  high_threshold float,
  training_metrics jsonb,
  updated_at timestamptz
);

-- OTP challenges
create table otp_challenges (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users,
  session_id text,
  otp_code text,
  status text default 'PENDING',
  created_at timestamptz default now(),
  expires_at timestamptz
);
```

### 4. Frontend setup

Update `BACKEND_URL` in `behavior.js`:

```js
const BACKEND_URL = "http://localhost:8000";  // local dev
// or
const BACKEND_URL = "https://cognivex-oul6.onrender.com";  // production
```

Then open `frontend/index.html` via a local server (VS Code Live Server, or `python -m http.server`).

---

## ▶️ Running the App

```bash
# From project root
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

Visit the interactive API docs at: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

## 📡 API Reference

### `POST /session/snapshot`
Receives a 30-second behavioral snapshot and returns a risk assessment.

```json
// Request
{
  "user_id": "uuid",
  "session_id": "uuid",
  "key_events": [{ "type": "keyup", "key": "a", "timestamp": "..." }],
  "mouse_events": [{ "type": "MOVE", "x": 120, "y": 340, "timestamp": "..." }],
  "scroll_events": [{ "type": "SCROLL", "y": 800, "timestamp": "..." }],
  "summary": {}
}

// Response — LOW
{ "status": "OK", "risk_level": "LOW", "score": 0.042, "model_version": 3 }

// Response — MEDIUM
{ "status": "OTP_REQUIRED", "risk_level": "MEDIUM", "session_id": "...", "score": -0.021 }

// Response — HIGH
{ "status": "SESSION_TERMINATED", "risk_level": "HIGH", "score": -0.091 }
```

### `POST /session/end`
Aggregates LOW-risk snapshots into a feature row and triggers model training if needed.

```json
// Request
{ "user_id": "uuid", "session_id": "uuid" }

// Response
{ "status": "SESSION_STORED" }
// or
{ "status": "MODEL_TRAINED", "model_version": 1, "trained_on": 15 }
// or
{ "status": "MODEL_RETRAINED", "model_version": 4, "trained_on": 45, "window_type": "sliding" }
```

### `POST /verify-otp`
Verifies a 6-digit OTP code submitted after a MEDIUM-risk challenge.

```json
// Request
{ "user_id": "uuid", "session_id": "uuid", "otp_code": "482910" }

// Success
{ "status": "OTP_VERIFIED", "grace_period_minutes": 10 }

// Failure
{ "status": "SESSION_TERMINATED", "risk_level": "HIGH", "detail": "wrong_otp_code" }
```

### `GET /status/{user_id}`
Returns the current model state for a user.

```json
{
  "model_version": 3,
  "total_sessions": 28,
  "last_risk_level": "LOW",
  "medium_threshold": -0.018,
  "high_threshold": -0.074
}
```

### `GET /health`
```json
{ "status": "ok", "version": "2.0.0" }
```

---

## 🧪 Postman API Testing

An automated Postman collection is included in `postman/cognivex_otp_flow.postman_collection.json` to test the OTP re-tagging flow, health checks, risk thresholds, and grace period logic.

### Setup Instructions

1. **Import the Collection**:
   - In Postman, click **File > Import** and select `postman/cognivex_otp_flow.postman_collection.json`.

2. **Set Up Local Environment**:
   - Copy the environment template:
     ```bash
     cp postman/cognivex-local.postman_environment.example.json postman/cognivex-local.postman_environment.json
     ```
   - Import `postman/cognivex-local.postman_environment.json` into Postman via **File > Import**.
   - Select **Cognivex Local Environment** from the top-right environment dropdown.

3. **Configure Environment Variables**:
   - `base_url`: Target backend URL (default: `http://localhost:8000`).
   - `test_email`: Email address for test authentication.
   - `test_password`: Password for test authentication.
   - `supabase_url`: Your Supabase project URL (e.g., `https://your-project.supabase.co`).
   - `supabase_anon_key`: Your Supabase anon public API key.
   - `user_id`: Automatically populated when running Request #2 (Supabase Auth Login), or set manually.
   - `session_id`: Automatically generated during testing (`postman-test-{{$timestamp}}`).
   - `log_id`: Automatically saved when Request #4 triggers a `MEDIUM` risk response.
   - `otp_code`: Paste the verification code received via email before running Request #5 (`/verify-otp`).

---

## 🚢 Deployment

| Layer | Platform | Notes |
|---|---|---|
| Frontend | [Vercel](https://vercel.com) | Static site, set Root Directory to `frontend/` |
| Backend | [Render](https://render.com) | Free tier, set start command to `uvicorn main:app --host 0.0.0.0 --port $PORT` |
| Database | [Supabase](https://supabase.com) | Free tier covers this project comfortably |
| Email | [Resend](https://resend.com) | 3,000 free emails/month — SMTP is blocked on Render free tier |

After deploying, update CORS in `main.py`:
```python
allow_origins=["https://your-frontend.vercel.app"]
```

And in Supabase → Authentication → URL Configuration:
```
Site URL:      https://your-frontend.vercel.app
Redirect URLs: https://your-frontend.vercel.app/**
```

---

## 🤝 Contributing

Contributions are welcome!

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Commit your changes: `git commit -m "Add your feature"`
4. Push to the branch: `git push origin feature/your-feature`
5. Open a Pull Request

---

## 📄 License

This project is for educational and research purposes.

---

<div align="center">
Built with FastAPI · Supabase · IsolationForest · Vercel · Render
</div>
