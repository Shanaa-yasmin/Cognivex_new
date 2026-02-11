"""
USER PROFILE BUILDER
===================

Simple, clean Python code to:
1. Fetch 8 behavior sessions from Supabase
2. Calculate statistics (mean and std dev)
3. Create and store user profile in database

Usage:
    python build_profile.py

Environment Variables Required:
    SUPABASE_URL - Your Supabase project URL
    SUPABASE_SERVICE_KEY - Your Supabase service role key
"""

import os
import sys
from typing import Optional, Dict, List, Tuple
import numpy as np
from supabase import create_client, Client
from dotenv import load_dotenv
load_dotenv()


# ============================================
# CONSTANTS
# ============================================

FEATURE_NAMES = [
    'typing_speed',
    'backspace_ratio',
    'avg_keystroke_interval',
    'keystroke_variance',
    'avg_mouse_speed',
    'mouse_move_variance',
    'scroll_frequency',
    'idle_ratio'
]

MIN_SESSIONS_REQUIRED = 8
DATA_QUALITY_THRESHOLD = 0.85


# ============================================
# SUPABASE CONNECTION
# ============================================

class SupabaseConnection:
    """Handle all Supabase operations"""
    
    def __init__(self):
        """Initialize Supabase client"""
        self.url = os.getenv("SUPABASE_URL")
        self.key = os.getenv("SUPABASE_SERVICE_KEY")

        
        if not self.url or not self.key:
            self._print_error("Missing environment variables!")
            self._print_error("Set SUPABASE_URL and SUPABASE_SERVICE_KEY")
            sys.exit(1)
        
        self.client: Client = create_client(self.url, self.key)
        self._print_success("Connected to Supabase")
    
    def fetch_sessions(self, user_id: str, num_sessions: int = 8) -> Optional[List[Dict]]:
        """
        Fetch user's behavior sessions from database
        
        Args:
            user_id: The user's UUID
            num_sessions: Number of sessions to fetch (default 8)
        
        Returns:
            List of session records or None if error
        """
        self._print_info(f"Fetching {num_sessions} sessions for user: {user_id}")
        
        try:
            response = (
                self.client
                .table('behavior_features')
                .select('*')
                .eq('user_id', user_id)
                .order('generated_at', desc=True)
                .limit(num_sessions)
                .execute()
            )
            
            sessions = response.data
            
            if not sessions:
                self._print_error(f"No sessions found for user {user_id}")
                return None
            
            self._print_success(f"Found {len(sessions)} sessions")
            return sessions
        
        except Exception as e:
            self._print_error(f"Error fetching sessions: {str(e)}")
            return None
    
    def save_profile(self, profile: Dict) -> bool:
        """
        Save user profile to database
        
        Args:
            profile: Profile dictionary to save
        
        Returns:
            True if successful, False otherwise
        """
        self._print_info("Saving profile to database...")
        
        try:
            self.client.table('user_profiles').insert(profile).execute()
            self._print_success("Profile saved successfully!")
            return True
        
        except Exception as e:
            self._print_error(f"Error saving profile: {str(e)}")
            return False
    
    @staticmethod
    def _print_success(msg: str):
        """Print success message"""
        print(f"✅ {msg}")
    
    @staticmethod
    def _print_error(msg: str):
        """Print error message"""
        print(f"❌ {msg}")
    
    @staticmethod
    def _print_info(msg: str):
        """Print info message"""
        print(f"📊 {msg}")


# ============================================
# PROFILE BUILDER
# ============================================

class ProfileBuilder:
    """Build user behavioral profile from sessions"""
    
    def __init__(self):
        """Initialize profile builder"""
        self.supabase = SupabaseConnection()
    
    def build(self, user_id: str) -> Optional[Dict]:
        """
        Complete workflow to build user profile
        
        Args:
            user_id: The user's UUID
        
        Returns:
            Profile dictionary if successful, None otherwise
        """
        self._print_header("BUILDING USER PROFILE")
        
        # Step 1: Fetch sessions
        sessions = self.supabase.fetch_sessions(user_id, MIN_SESSIONS_REQUIRED)
        if not sessions or len(sessions) < 2:
            self._print_error(f"Need at least 2 sessions (found {len(sessions) if sessions else 0})")
            return None
        
        # Step 2: Extract features
        feature_matrix, _ = self._extract_features(sessions)
        
        # Step 3: Calculate statistics
        means = self._calculate_means(feature_matrix)
        stds = self._calculate_stds(feature_matrix)
        
        # Step 4: Create profile
        profile = self._create_profile(user_id, means, stds, len(sessions))
        
        # Step 5: Save to database
        if not self.supabase.save_profile(profile):
            return None
        
        # Step 6: Print summary
        self._print_summary(profile)
        
        return profile
    
    def _extract_features(self, sessions: List[Dict]) -> Tuple[np.ndarray, List[str]]:
        """
        Extract features from sessions into matrix
        
        Args:
            sessions: List of session records
        
        Returns:
            Tuple of (feature_matrix, feature_names)
        """
        print("\n🔍 Extracting features...")
        
        feature_matrix = []
        
        for i, session in enumerate(sessions):
            row = []
            for feature_name in FEATURE_NAMES:
                value = float(session.get(feature_name, 0))
                row.append(value)
            feature_matrix.append(row)
            print(f"   Session {i+1}: {len(row)} features extracted")
        
        feature_matrix = np.array(feature_matrix)
        print(f"✅ Extracted {feature_matrix.shape[0]}×{feature_matrix.shape[1]} matrix")
        
        return feature_matrix, FEATURE_NAMES
    
    def _calculate_means(self, feature_matrix: np.ndarray) -> np.ndarray:
        """Calculate mean for each feature"""
        print("\n📈 Calculating means...")
        
        means = np.mean(feature_matrix, axis=0)
        
        for i, name in enumerate(FEATURE_NAMES):
            print(f"   {name}: {means[i]:.6f}")
        
        return means
    
    def _calculate_stds(self, feature_matrix: np.ndarray) -> np.ndarray:
        """Calculate standard deviation for each feature"""
        print("\n📈 Calculating standard deviations...")
        
        stds = np.std(feature_matrix, axis=0)
        
        for i, name in enumerate(FEATURE_NAMES):
            print(f"   {name}: {stds[i]:.6f}")
        
        return stds
    
    def _create_profile(
        self, 
        user_id: str, 
        means: np.ndarray, 
        stds: np.ndarray, 
        num_sessions: int
    ) -> Dict:
        """
        Create profile dictionary
        
        Args:
            user_id: The user's UUID
            means: Array of mean values
            stds: Array of standard deviation values
            num_sessions: Number of sessions used
        
        Returns:
            Profile dictionary ready to save
        """
        print("\n✅ Creating profile...")
        
        # Calculate data quality score (0-1)
        # Lower variance = higher quality
        avg_std = np.mean(stds)
        quality_score = max(0, 1.0 - (avg_std * 0.5))
        quality_score = min(1.0, quality_score)  # Cap at 1.0
        
        profile = {
            'user_id': user_id,
            'sessions_used': num_sessions,
            'status': 'active',
            'data_quality_score': float(quality_score),
            'profile_version': 1,
            
            # Mean values
            'typing_speed_mean': float(means[0]),
            'backspace_ratio_mean': float(means[1]),
            'avg_keystroke_interval_mean': float(means[2]),
            'keystroke_variance_mean': float(means[3]),
            'avg_mouse_speed_mean': float(means[4]),
            'mouse_move_variance_mean': float(means[5]),
            'scroll_frequency_mean': float(means[6]),
            'idle_ratio_mean': float(means[7]),
            
            # Standard deviation values
            'typing_speed_std': float(stds[0]),
            'backspace_ratio_std': float(stds[1]),
            'avg_keystroke_interval_std': float(stds[2]),
            'keystroke_variance_std': float(stds[3]),
            'avg_mouse_speed_std': float(stds[4]),
            'mouse_move_variance_std': float(stds[5]),
            'scroll_frequency_std': float(stds[6]),
            'idle_ratio_std': float(stds[7]),
        }
        
        print(f"   User ID: {profile['user_id']}")
        print(f"   Sessions: {profile['sessions_used']}")
        print(f"   Quality: {profile['data_quality_score']:.2%}")
        
        return profile
    
    def _print_summary(self, profile: Dict):
        """Print profile summary"""
        print("\n" + "="*70)
        print("📊 PROFILE SUMMARY")
        print("="*70)
        
        print(f"\nUser: {profile['user_id']}")
        print(f"Sessions: {profile['sessions_used']}")
        print(f"Quality: {profile['data_quality_score']:.2%}")
        print(f"Status: {profile['status']}")
        
        print("\n📈 Behavioral Baseline (Mean ± Std Dev):")
        print("-"*70)
        
        features_display = [
            ('Typing Speed', 'typing_speed_mean', 'typing_speed_std'),
            ('Backspace Ratio', 'backspace_ratio_mean', 'backspace_ratio_std'),
            ('Keystroke Interval', 'avg_keystroke_interval_mean', 'avg_keystroke_interval_std'),
            ('Keystroke Variance', 'keystroke_variance_mean', 'keystroke_variance_std'),
            ('Mouse Speed', 'avg_mouse_speed_mean', 'avg_mouse_speed_std'),
            ('Mouse Variance', 'mouse_move_variance_mean', 'mouse_move_variance_std'),
            ('Scroll Frequency', 'scroll_frequency_mean', 'scroll_frequency_std'),
            ('Idle Ratio', 'idle_ratio_mean', 'idle_ratio_std'),
        ]
        
        for display_name, mean_key, std_key in features_display:
            mean = profile[mean_key]
            std = profile[std_key]
            print(f"  {display_name:20} = {mean:10.6f} ± {std:8.6f}")
        
        print("\n" + "="*70)
        print("✅ Profile ready for authentication verification!")
        print("="*70 + "\n")
    
    @staticmethod
    def _print_header(text: str):
        """Print section header"""
        print("\n" + "="*70)
        print(f"🎯 {text}")
        print("="*70)


# ============================================
# MAIN ENTRY POINT
# ============================================

def main():
    """Main function"""
    
    # Example: Build profile for a user
    # Replace 'user_id_here' with actual UUID
    user_id = "853e5e01-d7cb-49b9-8fb2-ecfd0b895e06"
    
    print("USER PROFILE BUILDER")
    print("=" * 70)
    
    builder = ProfileBuilder()
    profile = builder.build(user_id)
    
    if profile:
        print("\n✅ Profile built and saved successfully!")
        return 0
    else:
        print("\n❌ Failed to build profile")
        return 1


if __name__ == "__main__":
    exit(main())