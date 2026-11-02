"""Entry point for the packaged DeskMate.exe (same as `python -m deskmate`)."""

from deskmate.app import safe_main

raise SystemExit(safe_main())
