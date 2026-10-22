import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import monitor
from monitor import validate_config


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ConfigValidationTests(unittest.TestCase):
    def test_example_config_is_valid(self) -> None:
        with (PROJECT_ROOT / "config.example.json").open(
            "r", encoding="utf-8"
        ) as config_file:
            config = json.load(config_file)

        validate_config(config)

    def test_root_must_be_an_object(self) -> None:
        with self.assertRaisesRegex(ValueError, "JSON nesnesi"):
            validate_config([])

    def test_check_section_must_be_a_list(self) -> None:
        with self.assertRaisesRegex(ValueError, "websites bir liste olmalıdır"):
            validate_config({"websites": {"url": "https://example.com"}})

    def test_required_fields_are_reported_together(self) -> None:
        config = {
            "websites": [{}],
            "linux_servers": [{"host": "", "user": ""}],
        }

        with self.assertRaises(ValueError) as context:
            validate_config(config)

        message = str(context.exception)
        self.assertIn("websites[0].url", message)
        self.assertIn("linux_servers[0].host", message)
        self.assertIn("linux_servers[0].user", message)

    def test_numeric_ranges_are_validated(self) -> None:
        config = {
            "ping_hosts": [{"host": "127.0.0.1", "timeout_ms": 0}],
            "disk_paths": [{"path": ".", "warn_free_percent": 101}],
            "linux_servers": [
                {
                    "host": "example.com",
                    "user": "monitor",
                    "port": 70000,
                    "timeout_sec": "invalid",
                }
            ],
        }

        with self.assertRaises(ValueError) as context:
            validate_config(config)

        message = str(context.exception)
        self.assertIn("ping_hosts[0].timeout_ms", message)
        self.assertIn("disk_paths[0].warn_free_percent", message)
        self.assertIn("linux_servers[0].port", message)
        self.assertIn("linux_servers[0].timeout_sec", message)

    def test_boolean_fields_require_json_booleans(self) -> None:
        config = {
            "send_only_on_alert": "false",
            "backup_folders": [{"path": ".", "recursive": "true"}],
        }

        with self.assertRaises(ValueError) as context:
            validate_config(config)

        message = str(context.exception)
        self.assertIn("send_only_on_alert", message)
        self.assertIn("backup_folders[0].recursive", message)

    @patch("monitor.build_report")
    @patch("monitor.load_config")
    @patch("monitor.parse_args")
    def test_invalid_config_stops_before_checks_start(
        self,
        parse_args_mock,
        load_config_mock,
        build_report_mock,
    ) -> None:
        parse_args_mock.return_value = SimpleNamespace(config=Path("invalid.json"))
        load_config_mock.return_value = {"websites": [{}]}

        with self.assertRaises(ValueError):
            monitor.main()

        build_report_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
