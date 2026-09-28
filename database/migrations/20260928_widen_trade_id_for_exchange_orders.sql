-- Exchange order IDs are not limited to eight characters.
ALTER TABLE public.trades
    ALTER COLUMN id TYPE TEXT USING id::text;
