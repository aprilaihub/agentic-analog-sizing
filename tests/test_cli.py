from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout

from agentic_sizing.cli import main


class TestCLI(unittest.TestCase):
    def test_top_level_help_lists_only_public_commands(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            main(["--help"])

        self.assertEqual(raised.exception.code, 0)
        self.assertNotIn("extract-specs", output.getvalue())

    def test_run_help_is_dispatched_to_run_parser(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            main(["run", "--help"])

        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--netlist", output.getvalue())
        self.assertIn("--mode", output.getvalue())


if __name__ == "__main__":
    unittest.main()
