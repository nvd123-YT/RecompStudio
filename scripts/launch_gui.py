"""Packaged desktop entrypoint with a non-Tk startup error fallback."""
from recompstudio.startup import main

if __name__ == "__main__":
    raise SystemExit(main())
