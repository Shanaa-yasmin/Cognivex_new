console.log('Initializing Supabase...');

if (!window.supabaseClient) {
    const SUPABASE_URL = 'https://driblaepjoebknxymfzh.supabase.co';
    const SUPABASE_ANON_KEY = 'sb_publishable_PqmcU2v1bs1B3ef-x22hiQ_nFNpRUhw';

    // 'supabase' comes from the CDN loaded in HTML
    window.supabaseClient = supabase.createClient(
        SUPABASE_URL,
        SUPABASE_ANON_KEY,
        {
            auth: {
                autoRefreshToken: true,
                persistSession: true,
                detectSessionInUrl: true
            }
        }
    );
    console.log('✓ Supabase client created successfully');
} else {
    console.log('✅ Supabase client already initialized');
}

window.supabaseHelper = {
    async insertBehaviorData(data) {
        try {
            const supabase = window.supabaseClient;
            const { data: result, error } = await supabase
                .from('behavior_logs')
                .insert([data]);

            if (error) throw error;
            console.log('✅ behavior_logs inserted');
            return { success: true, result };
        } catch (error) {
            console.error('❌ behavior_logs insert failed:', error.message);
            return { success: false, error };
        }
    },

    async insertBehaviorFeatures(userId, features) {
        try {
            const supabase = window.supabaseClient;
            
            const { data: result, error } = await supabase
                .from('behavior_features')
                .insert([{
                    user_id: userId,
                    session_id: features.session_id,
                    typing_speed: features.typing_speed,
                    backspace_ratio: features.backspace_ratio,
                    avg_keystroke_interval: features.avg_keystroke_interval,
                    keystroke_variance: features.keystroke_variance,
                    avg_mouse_speed: features.avg_mouse_speed,
                    mouse_move_variance: features.mouse_move_variance,
                    scroll_frequency: features.scroll_frequency,
                    idle_ratio: features.idle_ratio,
                    total_windows: features.total_windows,
                    generated_at: features.generated_at
                }]);

            if (error) throw error;
            console.log('✅ behavior_features inserted');
            return { success: true, result };
        } catch (error) {
            console.error('❌ behavior_features insert failed:', error.message);
            return { success: false, error };
        }
    },

    async getUserId() {
        try {
            const supabase = window.supabaseClient;
            const { data: { session }, error } = await supabase.auth.getSession();
            
            if (error || !session) {
                console.warn('⚠️ No active session');
                return null;
            }
            
            return session.user.id;
        } catch (error) {
            console.error('❌ Error getting user ID:', error);
            return null;
        }
    }
};