"""Cross-platform startup diagnostics and packaged-app smoke tests.

The launcher creates its log before importing the GUI and enables faulthandler,
so both Python exceptions and fatal interpreter signals leave diagnostics.
"""
from __future__ import annotations

import atexit
import faulthandler
import os
import platform
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


_CRASH_LOG_STREAM = None
_CRASH_LOG_PATH: Path | None = None
_SHUTDOWN_HOOK_REGISTERED = False


def startup_log_path() -> Path:
    override = os.environ.get("RECOMPSTUDIO_STARTUP_LOG")
    if override:
        return Path(override).expanduser()

    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
        base = base / "RecompStudio" / "Logs"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Logs" / "RecompStudio"
    else:
        state_home = os.environ.get("XDG_STATE_HOME")
        base = (Path(state_home).expanduser() if state_home
                else Path.home() / ".local" / "state")
        base = base / "RecompStudio"
    return base / "startup.log"


def begin_startup_session() -> Path:
    """Create the diagnostic file immediately and capture fatal Python signals."""
    global _CRASH_LOG_STREAM, _CRASH_LOG_PATH, _SHUTDOWN_HOOK_REGISTERED
    if _CRASH_LOG_STREAM is not None and _CRASH_LOG_PATH is not None:
        return _CRASH_LOG_PATH

    candidates = [
        startup_log_path(),
        Path(tempfile.gettempdir()) / "RecompStudio-startup.log",
    ]
    for path in candidates:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            stream = path.open("a", encoding="utf-8", buffering=1)
            stream.write(
                f"\n{'=' * 72}\n"
                f"Application starting: {datetime.now(timezone.utc).isoformat()}\n"
                f"Platform: {platform.platform()}\n"
                f"Python: {sys.version}\n"
                f"Executable: {sys.executable}\n"
                f"Arguments: {sys.argv!r}\n"
            )
            stream.flush()
            _CRASH_LOG_STREAM = stream
            _CRASH_LOG_PATH = path
            try:
                faulthandler.enable(file=stream, all_threads=True)
            except (OSError, RuntimeError, ValueError):
                stream.write("Warning: faulthandler could not be enabled.\n")
            if not _SHUTDOWN_HOOK_REGISTERED:
                atexit.register(_finish_startup_session)
                _SHUTDOWN_HOOK_REGISTERED = True
            return path
        except OSError:
            continue
    return candidates[-1]


def _finish_startup_session() -> None:
    """Record a normal exit; a fatal crash will instead be written by faulthandler."""
    global _CRASH_LOG_STREAM, _CRASH_LOG_PATH
    stream = _CRASH_LOG_STREAM
    if stream is None:
        return
    try:
        stream.write(
            f"Process exited normally: {datetime.now(timezone.utc).isoformat()}\n"
        )
        stream.flush()
    except (OSError, ValueError):
        pass
    try:
        faulthandler.disable()
    except (RuntimeError, OSError):
        pass
    try:
        stream.close()
    except OSError:
        pass
    _CRASH_LOG_STREAM = None
    _CRASH_LOG_PATH = None


def close_startup_session() -> None:
    """Close a diagnostic session explicitly (also used by unit tests)."""
    _finish_startup_session()


def _write_startup_note(message: str) -> None:
    stream = _CRASH_LOG_STREAM
    if stream is None:
        return
    try:
        stream.write(f"{datetime.now(timezone.utc).isoformat()} {message}\n")
        stream.flush()
    except (OSError, ValueError):
        pass


def record_exception(
    exception: BaseException,
    *,
    context: str = "Application startup",
    exc_traceback=None,
) -> Path:
    """Append a traceback to a stable per-user log, with a temp fallback."""
    trace = "".join(traceback.format_exception(
        type(exception), exception,
        exc_traceback if exc_traceback is not None else exception.__traceback__,
    ))
    body = (
        f"\n{'=' * 72}\n"
        f"Time (UTC): {datetime.now(timezone.utc).isoformat()}\n"
        f"Context: {context}\n"
        f"Platform: {platform.platform()}\n"
        f"Python: {sys.version}\n"
        f"Executable: {sys.executable}\n"
        f"Arguments: {sys.argv!r}\n\n"
        f"{trace}"
    )
    candidates = [startup_log_path(), Path(tempfile.gettempdir()) / "RecompStudio-startup.log"]
    for path in candidates:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(body)
            return path
        except OSError:
            continue
    return candidates[-1]


def startup_error_message(log_path: Path) -> str:
    return (
        "RecompStudio could not start.\n\n"
        "Please try reopening the app once. If it still fails, attach this "
        "diagnostic log when reporting the problem:\n\n"
        f"{log_path}"
    )


def show_startup_error(log_path: Path) -> None:
    """Display an error without relying on Tk, which may be the failing part."""
    message = startup_error_message(log_path)
    title = "RecompStudio could not start"

    if sys.platform == "darwin":
        escaped = message.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        script = (
            f'display dialog "{escaped}" with title "{title}" '
            'buttons {"Quit"} default button "Quit" with icon stop'
        )
        try:
            subprocess.run(
                ["/usr/bin/osascript", "-e", script],
                check=False, timeout=30, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
        except (OSError, subprocess.TimeoutExpired):
            pass

    elif sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
            return
        except Exception:
            pass

    else:
        for command in ("zenity", "kdialog"):
            executable = None
            for candidate in os.environ.get("PATH", "").split(os.pathsep):
                path = Path(candidate) / command
                if path.is_file() and os.access(path, os.X_OK):
                    executable = str(path)
                    break
            if not executable:
                continue
            arguments = (
                [executable, "--error", "--title", title, "--text", message]
                if command == "zenity"
                else [executable, "--error", message, "--title", title]
            )
            try:
                subprocess.run(
                    arguments, check=False, timeout=30,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                return
            except (OSError, subprocess.TimeoutExpired):
                continue

    try:
        sys.stderr.write(message + "\n")
        sys.stderr.flush()
    except Exception:
        pass


def report_exception(
    exception: BaseException,
    *,
    context: str = "Application startup",
    exc_traceback=None,
    show_dialog: bool = True,
) -> Path:
    path = record_exception(
        exception, context=context, exc_traceback=exc_traceback,
    )
    if show_dialog:
        show_startup_error(path)
    return path


def startup_smoke_test() -> None:
    """Exercise the real GUI constructor and verify packaged resources."""
    import tkinter as tk

    from .bundles import bundle_manifest, bundle_root, bundled_toolchain
    from .registry import frameworks

    resource_root = bundle_root()
    if resource_root is None:
        raise RuntimeError(
            "The packaged framework bundle could not be located. "
            "The application cannot initialize its bundled catalog."
        )
    manifest = bundle_manifest()
    if not manifest.get("frameworks"):
        raise RuntimeError("The packaged framework manifest is empty or unreadable.")
    if bundled_toolchain() is None:
        raise RuntimeError("The packaged compiler toolchain archive is missing.")

    catalog = frameworks()
    if not catalog:
        raise RuntimeError(
            "The framework catalog is missing or empty. "
            "Expected recompstudio/data/frameworks.json in the packaged app."
        )

    # Exercise the same constructor that Finder / the desktop launcher runs.
    # This catches missing package data and GUI initialization failures that a
    # Tk-only smoke test cannot detect.
    from .gui import RecompStudioApp

    root = tk.Tk()
    root.withdraw()
    try:
        tk_version = str(root.tk.call("info", "patchlevel"))
        app = RecompStudioApp(root)
        root.update_idletasks()
        root.after(180, root.quit)
        root.mainloop()
        rendered_rows = len(app.framework_table.get_children())
        if rendered_rows != len(catalog):
            raise RuntimeError(
                f"The GUI loaded {rendered_rows} of {len(catalog)} catalog entries."
            )
    finally:
        root.destroy()

    report_path = os.environ.get("RECOMPSTUDIO_STARTUP_SMOKE_REPORT")
    if report_path:
        Path(report_path).write_text(
            f"Tk {tk_version}\nBundle: {resource_root}\n"
            f"Frameworks: {len(manifest['frameworks'])}\n"
            f"Catalog entries: {len(catalog)}\n"
            f"GUI rows: {rendered_rows}\n",
            encoding="utf-8",
        )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    begin_startup_session()
    try:
        if "--startup-smoke-test" in arguments:
            startup_smoke_test()
            _write_startup_note("Packaged GUI startup smoke test passed.")
            return 0
        from .gui import launch
        launch()
        _write_startup_note("GUI event loop exited normally.")
        return 0
    except Exception as exc:
        report_exception(exc, context="Application launch")
        return 1
