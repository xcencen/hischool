"""Inject Docker CLI timeout without creating or deleting actual containers."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("rehearsal", Path(__file__).resolve().parents[1]/"rehearse_assistant_release.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CleanupTests(unittest.TestCase):
    def exercise(self, failed_cleanup):
        parent = Path('F:/my-campus-dev/temp/m5-release/cleanup-tests')
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as folder:
            output = Path(folder)/'run'
            calls = []
            def fake(command, **kwargs):
                calls.append(command)
                if command[1:3] == ['run', '--name']:
                    raise subprocess.TimeoutExpired(command, 60)
                if command[1:3] == ['container','inspect']:
                    return subprocess.CompletedProcess(command, 0 if '--format' in command else 1,
                        ('my-campus-ai-m6-release'+'\n').encode(), b'')
                if command[1:3] == ['rm','-f'] and failed_cleanup:
                    raise subprocess.CalledProcessError(1, command)
                data = b'{}'
                if 'ps' in command:
                    data = b''
                if 'exec' in command and 'test-mysql' in command:
                    data = b'CREATE TABLE `users`; CREATE TABLE `alembic_version`;'
                return subprocess.CompletedProcess(command, 0, data, b'')
            expected = RuntimeError if failed_cleanup else subprocess.TimeoutExpired
            with patch.object(sys, 'argv', ['rehearsal','--output',str(output)]), patch.object(module.subprocess,'run',side_effect=fake), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(expected): module.main()
            report = json.loads((output/'report.json').read_text())
            self.assertFalse(report['passed'])
            self.assertTrue(any(c[1:3] == ['rm','-f'] for c in calls))
            if failed_cleanup:
                self.assertEqual(report['cleanup_failure'], 'CalledProcessError')
            else:
                self.assertTrue(any(c[-1] == 'down' for c in calls))

    def test_cli_timeout_removes_owned_probe_and_saves_failure_report(self):
        self.exercise(False)

    def test_cleanup_failure_still_saves_failure_report(self):
        self.exercise(True)


if __name__ == '__main__': unittest.main()
