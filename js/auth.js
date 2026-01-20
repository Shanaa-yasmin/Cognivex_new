window.authHandler = {

    isLoginPage() {
        return window.location.pathname.includes('index.html') ||
               window.location.pathname === '/' ||
               window.location.pathname.endsWith('/');
    },

    init() {
        console.log('🔐 Auth handler initializing...');
        this.checkSession();
        
        // Check session every 60 seconds
        this.sessionInterval = setInterval(() => {
            this.checkSession();
        }, 60000);

        // Check session when tab becomes visible
        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'visible') {
                this.checkSession();
            }
        });
    },

    async checkSession() {
        try {
            const supabase = window.supabaseClient;

            if (!supabase) {
                console.error('✗ Supabase client not available');
                return;
            }

            const { data, error } = await supabase.auth.getSession();
            if (error) throw error;

            const session = data.session;

            if (session) {
                console.log('✓ Active session found:', session.user.email);
                if (this.isLoginPage()) {
                    console.log('→ User already logged in, redirecting to dashboard...');
                    window.location.href = 'dashboard.html';
                }
            } else {
                console.log('✗ No active session found');
                if (!this.isLoginPage()) {
                    console.log('→ User not logged in, redirecting to login...');
                    window.location.href = 'index.html';
                }
            }

        } catch (error) {
            console.error('✗ Session check error:', error);
            if (!this.isLoginPage()) {
                window.location.href = 'index.html';
            }
        }
    },

    async login(email, password) {
        const errorMessage = document.getElementById('error-message');
        const loginButton = document.querySelector('#loginForm button[type="submit"]');
        const originalButtonText = loginButton?.textContent || 'Sign In';

        try {
            if (loginButton) {
                loginButton.disabled = true;
                loginButton.textContent = 'Signing in...';
            }

            if (errorMessage) {
                errorMessage.textContent = '';
                errorMessage.classList.remove('visible');
            }

            const supabase = window.supabaseClient;
            if (!supabase) throw new Error('Authentication service not available');

            console.log('🔐 Attempting login for:', email);

            const { data, error } = await supabase.auth.signInWithPassword({
                email: email.trim(),
                password: password
            });

            if (error) throw error;

            console.log('✓ Login successful for:', email);
            
            // Brief delay to ensure session is set
            setTimeout(() => {
                window.location.href = 'dashboard.html';
            }, 500);

        } catch (error) {
            console.error('✗ Login error:', error);

            if (errorMessage) {
                const userMessage = error.message.includes('Invalid login credentials')
                    ? '⚠ Invalid email or password. Please try again.'
                    : error.message || 'Login failed. Please try again.';
                
                errorMessage.textContent = userMessage;
                errorMessage.classList.add('visible');

                setTimeout(() => {
                    errorMessage.classList.remove('visible');
                }, 5000);
            }

        } finally {
            if (loginButton) {
                loginButton.disabled = false;
                loginButton.textContent = originalButtonText;
            }
        }
    },

    async logout() {
        try {
            console.log('🔐 Logging out...');
            const supabase = window.supabaseClient;
            
            if (!supabase) {
                window.location.href = 'index.html';
                return;
            }

            // Flush any remaining behavior data before logout
            if (window.flushBehaviorData) {
                await window.flushBehaviorData();
            }

            await supabase.auth.signOut();
            console.log('✓ Logout successful');
            
            window.location.href = 'index.html';

        } catch (error) {
            console.error('✗ Logout error:', error);
            window.location.href = 'index.html';
        }
    },

    getCurrentUser() {
        const supabase = window.supabaseClient;
        if (!supabase) return null;
        
        return supabase.auth.user();
    }
};

document.addEventListener('DOMContentLoaded', () => {
    console.log('📄 DOM loaded, initializing auth...');

    const waitForSupabase = setInterval(() => {
        if (window.supabaseClient) {
            clearInterval(waitForSupabase);
            window.authHandler.init();
        }
    }, 100);

    // Timeout after 5 seconds
    setTimeout(() => {
        if (window.supabaseClient) {
            window.authHandler.init();
        } else {
            console.error('✗ Supabase client failed to initialize after 5 seconds');
        }
    }, 5000);
});