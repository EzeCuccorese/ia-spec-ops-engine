"""Allow ``python -m ai_governance`` invocation for the background UI daemon."""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
