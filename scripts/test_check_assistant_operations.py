"""Run with stdlib unittest; no Docker or live configuration required."""
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
import io
import json
import subprocess
from check_assistant_operations import health_status, main


class HealthStatusTest(unittest.TestCase):
    def test_health_exit_codes(self):
        self.assertEqual(health_status([{"Service": "api", "State": "running", "Health": "healthy"}], ["api"])[0], 0)
        self.assertEqual(health_status([{"Service": "api", "State": "running", "Health": "unhealthy"}], ["api"])[0], 1)
        self.assertEqual(health_status([], ["api"])[0], 1)
        self.assertEqual(health_status([{"Service": "api", "State": "running", "Health": ""}], ["api"])[0], 2)

    def test_combined_exit_codes_and_safe_errors(self):
        args = ["--project", "synthetic", "--compose-file", "synthetic.yaml", "--service", "api"]
        health = subprocess.CompletedProcess([], 0, '[{"Service":"api","State":"running","Health":"healthy"}]', '')
        for expected, result in ((0, subprocess.CompletedProcess([], 0, '{"status":"ok"}', '')),
                                 (1, subprocess.CompletedProcess([], 1, '{"status":"warning"}', '')),
                                 (2, subprocess.CompletedProcess([], 2, '{"status":"unavailable"}', 'SECRET diagnostic')),
                                 (2, subprocess.CompletedProcess([], 0, '[]', 'SECRET diagnostic'))):
            output = io.StringIO()
            with patch("check_assistant_operations.subprocess.run", side_effect=[health, result]), redirect_stdout(output):
                self.assertEqual(main(args), expected)
            self.assertEqual(json.loads(output.getvalue())["status"], ("ok", "warning", "unavailable")[expected])
            self.assertNotIn("SECRET", output.getvalue())
        output = io.StringIO()
        with patch("check_assistant_operations.subprocess.run", side_effect=subprocess.TimeoutExpired("SECRET", 10)), redirect_stdout(output):
            self.assertEqual(main(args), 2)
        self.assertEqual(json.loads(output.getvalue()), {"status": "unavailable"})

    def test_docker_json_uses_utf8_on_chinese_windows(self):
        responses = iter([subprocess.CompletedProcess([],0,'[{"Service":"api","State":"running","Health":"healthy","Status":"已启动"}]',''),
                          subprocess.CompletedProcess([],0,'{"status":"ok"}','')])
        def execute(command, **options):
            self.assertEqual(options.get('encoding'), 'utf-8')
            return next(responses)
        with patch('check_assistant_operations.subprocess.run', side_effect=execute), redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--project','synthetic','--compose-file','synthetic.yaml','--service','api']),0)


if __name__ == "__main__":
    unittest.main()
