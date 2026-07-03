"""Pytest bootstrap for the nocturna-bot test suite.

Puts the repo root on ``sys.path`` so tests can import top-level packages
(e.g. ``core.image_optimize``, ``config``) the same way the bot does at runtime,
without needing an installed/editable package or a ``tests/__init__.py``.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
