#!/usr/bin/env python3
"""
Convenience launcher, so `python audit.py ...` keeps working.

The real entry point is the package: `python -m seo_audit`.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from seo_audit.cli import main

if __name__ == "__main__":
    main()
