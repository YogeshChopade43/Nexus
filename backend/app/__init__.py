import sys

if sys.version_info < (3, 10):
    raise SystemExit(
        f"Nexus needs Python 3.10 or newer (the MCP SDK requires it); this is Python "
        f"{sys.version_info.major}.{sys.version_info.minor} at {sys.executable}.\n"
        "Activate the 3.11 environment instead:  .\\.venv311\\Scripts\\Activate.ps1"
    )
