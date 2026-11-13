import os
import unittest
from unittest.mock import patch

from recompstudio.integrations import _command_environment


class FrameworkCommandEnvironmentTests(unittest.TestCase):
    def test_framework_overrides_keep_managed_and_toolchain_paths(self):
        sep = os.pathsep
        with patch("recompstudio.integrations.toolchain_environment",
                   return_value={"PATH": sep.join(["/compiler/bin", "/system/bin"])}):
            with patch("recompstudio.integrations.managed_environment",
                       side_effect=lambda env: {
                           **env, "PATH": sep.join(["/managed/gh", env["PATH"]])
                       }):
                env = _command_environment({
                    "PATH": sep.join(["/custom/bin", "/system/bin"]),
                    "FRAMEWORK_SETTING": "enabled",
                })
        self.assertEqual(
            env["PATH"].split(sep),
            ["/managed/gh", "/compiler/bin", "/custom/bin", "/system/bin"],
        )
        self.assertEqual(env["FRAMEWORK_SETTING"], "enabled")


if __name__ == "__main__":
    unittest.main()
