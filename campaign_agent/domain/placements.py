"""Shared YouTube video identifier syntax."""

import re


VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
