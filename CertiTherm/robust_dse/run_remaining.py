#!/usr/bin/env python3
"""Compatibility entry point for the corrected sampled-stress pilot."""

try:
    from .sample_worst_case import main
except ImportError:
    from sample_worst_case import main


if __name__ == '__main__':
    raise SystemExit(main())
