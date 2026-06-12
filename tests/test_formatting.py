# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

BASE_DIR = Path(__file__).resolve().parent.parent


class FormattingTest(SimpleTestCase):
    def test_ruff_format(self):
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "format", "--check", str(BASE_DIR)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"ruff format --check failed (run `ruff format .` to fix):\n{result.stdout}{result.stderr}",
        )

    def test_ruff_lint(self):
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "check", str(BASE_DIR)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"ruff check failed (run `ruff check --fix .` to fix):\n{result.stdout}{result.stderr}",
        )
