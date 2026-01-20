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

    console.log('Supabase client created successfully');
} else {
    console.log('Supabase client already initialized');
}
