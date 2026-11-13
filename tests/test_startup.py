import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from recompstudio.startup import (
    begin_startup_session, close_startup_session, record_exception,
    startup_error_message, startup_log_path,
)


class StartupDiagnosticsTests(unittest.TestCase):
    def test_log_path_can_be_overridden_for_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "startup.log"
            with patch.dict(os.environ, {"RECOMPSTUDIO_STARTUP_LOG": str(target)}):
                self.assertEqual(startup_log_path(), target)

    def test_exception_is_logged_with_context_and_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "logs" / "startup.log"
            try:
                raise RuntimeError("Tk failed to initialize")
            except RuntimeError as exc:
                with patch.dict(os.environ, {"RECOMPSTUDIO_STARTUP_LOG": str(target)}):
                    written = record_exception(exc, context="test launch")
            content = written.read_text(encoding="utf-8")
            self.assertIn("test launch", content)
            self.assertIn("RuntimeError: Tk failed to initialize", content)

    def test_startup_session_creates_the_log_before_launch(self):
        close_startup_session()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "logs" / "startup.log"
            with patch.dict(os.environ, {"RECOMPSTUDIO_STARTUP_LOG": str(target)}):
                try:
                    written = begin_startup_session()
                    self.assertEqual(written, target)
                    self.assertTrue(target.is_file())
                    content = target.read_text(encoding="utf-8")
                    self.assertIn("Application starting:", content)
                    self.assertIn("Executable:", content)
                finally:
                    close_startup_session()

    def test_reopen_guidance_includes_exact_log_path(self):
        target = Path("/tmp/recompstudio-startup.log")
        message = startup_error_message(target)
        self.assertIn("try reopening the app once", message)
        self.assertIn(str(target), message)
