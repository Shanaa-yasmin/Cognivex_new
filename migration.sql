-- ============================================================
-- MIGRATION SCRIPT — Run this in Supabase SQL Editor
-- ============================================================

-- 1. ALTER behavior_logs: add session_id, risk_level, model_version
ALTER TABLE behavior_logs
  ADD COLUMN IF NOT EXISTS session_id varchar,
  ADD COLUMN IF NOT EXISTS risk_level varchar,
  ADD COLUMN IF NOT EXISTS model_version integer;

-- 2. Create unique index on behavior_logs(session_id) for FK reference
--    (session_id is NOT unique per row — multiple snapshots share a session)
--    We do NOT add a unique constraint; behavior_features.session_id references
--    behavior_logs loosely via application logic.

-- 3. Create model_metadata table
CREATE TABLE IF NOT EXISTS model_metadata (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  model_version integer NOT NULL DEFAULT 1,
  model_bytes text,
  total_sessions integer,
  last_trained_count integer,
  updated_at timestamptz DEFAULT now()
);

-- 4. Create otp_challenges table
CREATE TABLE IF NOT EXISTS otp_challenges (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  session_id varchar NOT NULL,
  otp_code varchar NOT NULL DEFAULT '2323',
  status varchar DEFAULT 'PENDING',
  created_at timestamptz DEFAULT now(),
  expires_at timestamptz
);

-- 5. Enable RLS on new tables
ALTER TABLE model_metadata ENABLE ROW LEVEL SECURITY;
ALTER TABLE otp_challenges ENABLE ROW LEVEL SECURITY;

-- 6. RLS policies for model_metadata
CREATE POLICY "Users can read own model_metadata"
  ON model_metadata FOR SELECT
  USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own model_metadata"
  ON model_metadata FOR INSERT
  WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own model_metadata"
  ON model_metadata FOR UPDATE
  USING (auth.uid() = user_id);

-- 7. RLS policies for otp_challenges
CREATE POLICY "Users can read own otp_challenges"
  ON otp_challenges FOR SELECT
  USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own otp_challenges"
  ON otp_challenges FOR INSERT
  WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own otp_challenges"
  ON otp_challenges FOR UPDATE
  USING (auth.uid() = user_id);

-- 8. Service role policies (for backend with service key)
CREATE POLICY "Service can manage model_metadata"
  ON model_metadata FOR ALL
  USING (true)
  WITH CHECK (true);

CREATE POLICY "Service can manage otp_challenges"
  ON otp_challenges FOR ALL
  USING (true)
  WITH CHECK (true);

-- 9. Index for faster queries
CREATE INDEX IF NOT EXISTS idx_behavior_logs_user_session
  ON behavior_logs(user_id, session_id);

CREATE INDEX IF NOT EXISTS idx_behavior_logs_user_created
  ON behavior_logs(user_id, created_at);

CREATE INDEX IF NOT EXISTS idx_behavior_features_user
  ON behavior_features(user_id);

CREATE INDEX IF NOT EXISTS idx_model_metadata_user
  ON model_metadata(user_id);

CREATE INDEX IF NOT EXISTS idx_otp_challenges_user_session
  ON otp_challenges(user_id, session_id);
