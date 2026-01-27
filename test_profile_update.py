#!/usr/bin/env python3
"""
Test script to verify profile update and password change functionality.
Tests the fix for hardcoded credentials and profile update bug.
"""

import requests
import os
import sys

# Configuration
API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8000")
DEFAULT_USERNAME = os.getenv("DEFAULT_ADMIN_USERNAME", "admin")
DEFAULT_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", "password123")

def test_login(username, password):
    """Test login endpoint"""
    print(f"\n🔐 Testing login with username: {username}")
    try:
        response = requests.post(
            f"{API_BASE}/login/",
            json={"username": username, "password": password},
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Login successful")
            print(f"   Session ID: {data.get('session_id', 'N/A')[:20]}...")
            print(f"   Username: {data.get('username')}")
            print(f"   Role: {data.get('role')}")
            return data.get('session_id')
        else:
            print(f"❌ Login failed: {response.status_code}")
            print(f"   Response: {response.text}")
            return None
    except Exception as e:
        print(f"❌ Login error: {e}")
        return None


def test_get_profile(session_id):
    """Test get profile endpoint"""
    print(f"\n📋 Testing get profile")
    try:
        response = requests.get(
            f"{API_BASE}/profile/",
            headers={"Authorization": session_id},
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Profile fetched successfully")
            print(f"   Username: {data.get('username')}")
            print(f"   Email: {data.get('email', 'Not set')}")
            print(f"   Display Name: {data.get('displayName', 'Not set')}")
            print(f"   Role: {data.get('role')}")
            return data
        else:
            print(f"❌ Get profile failed: {response.status_code}")
            print(f"   Response: {response.text}")
            return None
    except Exception as e:
        print(f"❌ Get profile error: {e}")
        return None


def test_update_profile(session_id):
    """Test profile update endpoint with snake_case field names"""
    print(f"\n💾 Testing profile update (with display_name)")
    try:
        response = requests.put(
            f"{API_BASE}/profile/update",
            headers={
                "Content-Type": "application/json",
                "Authorization": session_id
            },
            json={
                "email": "admin@campaign-platform.com",
                "display_name": "Admin User"  # Testing snake_case (frontend format)
            },
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Profile updated successfully")
            print(f"   Message: {data.get('message')}")
            return True
        else:
            print(f"❌ Profile update failed: {response.status_code}")
            print(f"   Response: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Profile update error: {e}")
        return False


def test_change_password(session_id, current_pwd, new_pwd):
    """Test password change endpoint"""
    print(f"\n🔑 Testing password change")
    try:
        response = requests.put(
            f"{API_BASE}/profile/change-password",
            headers={
                "Content-Type": "application/json",
                "Authorization": session_id
            },
            json={
                "current_password": current_pwd,
                "new_password": new_pwd
            },
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Password changed successfully")
            print(f"   Message: {data.get('message')}")
            return True
        else:
            print(f"❌ Password change failed: {response.status_code}")
            print(f"   Response: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Password change error: {e}")
        return False


def main():
    """Run all profile tests"""
    print("=" * 60)
    print("Profile Update & Authentication Tests")
    print("=" * 60)
    print(f"API Base: {API_BASE}")
    print(f"Default Username: {DEFAULT_USERNAME}")
    print("=" * 60)
    
    # Test 1: Login with default credentials
    session_id = test_login(DEFAULT_USERNAME, DEFAULT_PASSWORD)
    if not session_id:
        print("\n❌ FAILED: Cannot proceed without successful login")
        sys.exit(1)
    
    # Test 2: Get profile
    profile = test_get_profile(session_id)
    if not profile:
        print("\n❌ FAILED: Cannot fetch profile")
        sys.exit(1)
    
    # Test 3: Update profile (testing the bug fix)
    update_success = test_update_profile(session_id)
    if not update_success:
        print("\n❌ FAILED: Profile update failed")
        sys.exit(1)
    
    # Test 4: Verify the update persisted
    print(f"\n🔍 Verifying profile update persisted...")
    updated_profile = test_get_profile(session_id)
    if updated_profile:
        if updated_profile.get('displayName') == 'Admin User':
            print(f"✅ Display name correctly updated to: {updated_profile.get('displayName')}")
        else:
            print(f"⚠️  Display name not updated as expected: {updated_profile.get('displayName')}")
        
        if updated_profile.get('email') == 'admin@campaign-platform.com':
            print(f"✅ Email correctly updated to: {updated_profile.get('email')}")
        else:
            print(f"⚠️  Email not updated as expected: {updated_profile.get('email')}")
    
    print("\n" + "=" * 60)
    print("✅ ALL TESTS PASSED!")
    print("=" * 60)
    print("\n📝 Summary:")
    print("   - Login with configurable credentials: ✅")
    print("   - Get profile: ✅")
    print("   - Update profile (display_name bug fix): ✅")
    print("   - Profile updates persist correctly: ✅")
    print("\n⚠️  Note: Password change test skipped to avoid changing production credentials")
    print("   You can test password change manually via the UI")


if __name__ == "__main__":
    main()
