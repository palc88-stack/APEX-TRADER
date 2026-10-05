-- APEX-TRADER: observational Shadow Mode events.
-- Shadow events are analytics only and are never an order/fill authority.

ALTER TABLE public.strategy_learning_events
  DROP CONSTRAINT IF EXISTS strategy_learning_events_type_check;

ALTER TABLE public.strategy_learning_events
  ADD CONSTRAINT strategy_learning_events_type_check CHECK (
    event_type IN (
      'trade_outcome',
      'execution_error',
      'data_quality',
      'reconciliation',
      'shadow_signal'
    )
  );

ALTER TABLE public.strategy_learning_events
  ADD COLUMN IF NOT EXISTS idempotency_key TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS uq_strategy_learning_events_idempotency
  ON public.strategy_learning_events (idempotency_key)
  WHERE idempotency_key IS NOT NULL;

COMMENT ON COLUMN public.strategy_learning_events.outcome IS
  'Outcome label or shadow recommendation; shadow values are not executed decisions.';
