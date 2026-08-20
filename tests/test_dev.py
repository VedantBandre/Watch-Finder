"""Tests for the one-command development launcher."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import dev


class DevLauncherTests(unittest.TestCase):
    def test_server_commands_use_active_python_and_frontend_directory(self) -> None:
        backend, frontend = dev.server_commands(Path("/project"))

        self.assertEqual(backend[:3], [dev.sys.executable, "-m", "uvicorn"])
        self.assertIn("backend.main:app", backend)
        self.assertEqual(frontend, ["npm", "--prefix", "/project/frontend", "run", "dev"])

    def test_missing_setup_returns_actionable_messages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch("dev.importlib.util.find_spec", return_value=None),
                patch("dev.shutil.which", return_value=None),
            ):
                problems = dev.check_prerequisites(Path(directory))

        self.assertTrue(any("pip install" in problem for problem in problems))
        self.assertTrue(any("Node.js" in problem for problem in problems))
        self.assertTrue(any(".env" in problem for problem in problems))

    def test_complete_setup_has_no_problems(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").touch()
            (root / "frontend" / "node_modules" / ".bin").mkdir(parents=True)
            (root / "frontend" / "node_modules" / ".bin" / "vite").touch()
            with (
                patch("dev.importlib.util.find_spec", return_value=object()),
                patch("dev.shutil.which", return_value="/usr/bin/npm"),
            ):
                problems = dev.check_prerequisites(root)

        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
