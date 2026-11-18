#!/usr/bin/env python3
"""Launch the explicitly configured Google Ads test-account command."""
import os
from pathlib import Path
import sys


def main():
    # Keep the published script executable without importing a composition root.
    launcher = Path(__file__).resolve().parents[1] / 'campaign_agent/bootstrap/google_ads_cli.py'
    os.execv(sys.executable, [sys.executable, str(launcher), *sys.argv[1:]])


if __name__ == '__main__':
    main()
