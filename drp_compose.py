#!/usr/bin/env python3
"""Compatibility wrapper. Use `drpkit compose` (`compose` module: drpkit.compose)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if __name__ == "__main__":
    from drpkit.compose import main
    sys.exit(main())
else:
    import drpkit.compose as _impl
    sys.modules[__name__] = _impl
