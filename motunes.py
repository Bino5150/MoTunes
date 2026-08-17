#!/usr/bin/env python3
"""
MoTunes — iPhone Manager for Linux
Mo Thugs South
"""
import sys
import os

# Add app root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui.main_window import main

if __name__ == "__main__":
    main()
