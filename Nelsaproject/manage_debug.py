#!/usr/bin/env python
"""
Simple script to manage Django DEBUG setting for different environments.
Usage:
    python manage_debug.py dev    # Set DEBUG=True for development
    python manage_debug.py prod   # Set DEBUG=False for production
"""

import os
import sys

def set_debug_mode(mode):
    """Set the DEBUG environment variable."""
    if mode.lower() in ['dev', 'development', 'true']:
        os.environ['DJANGO_DEBUG'] = 'True'
        print("✅ DEBUG mode set to True (Development)")
    elif mode.lower() in ['prod', 'production', 'false']:
        os.environ['DJANGO_DEBUG'] = 'False'
        print("✅ DEBUG mode set to False (Production)")
    else:
        print("❌ Invalid mode. Use 'dev' or 'prod'")
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python manage_debug.py [dev|prod]")
        print("  dev  - Set DEBUG=True for development")
        print("  prod - Set DEBUG=False for production")
        sys.exit(1)
    
    mode = sys.argv[1]
    set_debug_mode(mode)
    
    # Show current setting
    current_debug = os.environ.get('DJANGO_DEBUG', 'True')
    print(f"Current DJANGO_DEBUG setting: {current_debug}")
    print("\nTo apply changes, restart your Django server.") 