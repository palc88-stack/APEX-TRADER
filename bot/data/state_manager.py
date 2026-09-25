# bot/data/state_manager.py - الكود الحالي (ناقص)
class StateManager:
    def __init__(self, config=None):
        self.config = config or {}
        # ❌ يقرأ من config dict فقط - لا يدعم Config object
        self.supabase_url = os.getenv("SUPABASE_URL", ...)
        self.supabase_key = os.getenv("SUPABASE_KEY", ...)
        self.client = None
        self._init_supabase_connection()

    # ❌ الدوال المفقودة:
    # - load_initial_state()
    # - update_heartbeat()
    # - reconstruct_position()
    # - mark_bot_stopped()
    # - get_active_positions(symbol)
