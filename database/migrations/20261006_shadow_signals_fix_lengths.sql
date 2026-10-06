-- Fix observed production/Testnet insertion failure: a valid Shadow value exceeded
-- the initial narrow varchar contract. This remains observation-only.
ALTER TABLE public.shadow_signals
  ALTER COLUMN timeframe TYPE VARCHAR(32),
  ALTER COLUMN candidate_action TYPE VARCHAR(32),
  ALTER COLUMN classification TYPE VARCHAR(32),
  ALTER COLUMN model_version TYPE VARCHAR(128),
  ALTER COLUMN exit_reason TYPE VARCHAR(128);
