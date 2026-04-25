"""
Main.py — thin shim preserved for backwards compatibility.

The actual entry point lives in main/entry.py now.  Anything that runs
`python Main.py` (or imports `main` from this file) keeps working.

You can also run the package directly:
    python -m main
"""

from main import main

if __name__ == "__main__":
    main()
