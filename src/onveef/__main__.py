"""Allow ``python -m onveef`` to run the command-line interface."""

from __future__ import annotations

from onveef.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
