import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication, QMessageBox

from omdrop_gui import MainWindow, parse_receivers


class OmdropTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait_for(self, condition, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            if condition():
                return
            time.sleep(0.01)
        self.fail("Timed out waiting for GUI state")

    def test_parse_receivers_and_unrecognized_lines(self):
        receivers, unknown = parse_receivers(
            'ABC123         "Jane\'s iPhone" ([fe80::1]:8770%awdl0)\n'
            'DEF456         "Jane\\"s iPhone" ([fe80::2]:8770%awdl0)\n'
            "unexpected output\n"
        )
        self.assertEqual(receivers[0], ("ABC123", "Jane's iPhone", "[fe80::1]:8770%awdl0"))
        self.assertEqual(receivers[1], ("DEF456", 'Jane"s iPhone', "[fe80::2]:8770%awdl0"))
        self.assertEqual(unknown, ["unexpected output"])

    def test_frozen_process_restores_library_path(self):
        with patch("sys.frozen", True, create=True):
            with patch.dict(os.environ, {"LD_LIBRARY_PATH": "/bundled", "LD_LIBRARY_PATH_ORIG": "/original"}):
                window = MainWindow()
                try:
                    self.assertEqual(window.radio.processEnvironment().value("LD_LIBRARY_PATH"), "/original")
                finally:
                    window.close()
            with patch.dict(os.environ, {"LD_LIBRARY_PATH": "/bundled"}):
                os.environ.pop("LD_LIBRARY_PATH_ORIG", None)
                window = MainWindow()
                try:
                    self.assertFalse(window.radio.processEnvironment().contains("LD_LIBRARY_PATH"))
                finally:
                    window.close()

    def test_radio_discovery_send_and_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "owly"
            executable.write_text(
                "#!/usr/bin/python3\n"
                "import json, os, signal, sys, time\n"
                "args = sys.argv[1:]\n"
                "with open(os.environ['FAKE_OWLY_LOG'], 'a') as f: f.write(json.dumps(args) + '\\n')\n"
                "if args == ['radio', 'up']:\n"
                " signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))\n"
                " print('awdl0 is up: fe80::1%awdl0 (aa). Ctrl-C takes it down.', file=sys.stderr, flush=True)\n"
                " while True: time.sleep(0.1)\n"
                "elif args[0] == 'browse':\n"
                " print('ABC123         \"Phone\" ([fe80::1]:8770%awdl0)')\n"
                "elif args[0] == 'send':\n"
                " if os.environ.get('FAKE_OWLY_DECLINE'):\n"
                "  print('declined'); sys.exit(1)\n"
                " print('delivered')\n"
            )
            executable.chmod(0o755)
            file_path = root / "-test file.txt"
            file_path.write_text("test")
            log_path = root / "calls"
            with patch.dict(os.environ, {"PATH": f"{root}:{os.environ['PATH']}", "FAKE_OWLY_LOG": str(log_path)}):
                window = MainWindow()
                try:
                    with patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Ok):
                        window.toggle_radio()
                    self.wait_for(lambda: window.radio_ready)
                    window.find_devices()
                    self.wait_for(lambda: window.targets.count() == 1)
                    window.targets.setCurrentRow(0)
                    window.file_path = str(file_path)
                    window.update_controls()
                    self.assertTrue(window.send_button.isEnabled())
                    window.send_file()
                    self.wait_for(lambda: "Transfer complete." in window.log.toPlainText())
                    with patch.dict(os.environ, {"FAKE_OWLY_DECLINE": "1"}):
                        window.send_file()
                        self.wait_for(lambda: "Transfer failed or was interrupted" in window.log.toPlainText())
                        self.assertIn("declined", window.log.toPlainText())
                    window.stop_radio()
                    self.wait_for(lambda: window.radio.state() == QProcess.ProcessState.NotRunning)
                    self.assertFalse(window.radio_ready)
                    self.assertEqual(window.targets.count(), 0)
                    window.browse_output = 'ABC123 "Phone" ([fe80::1]:8770%awdl0)'
                    window.browse_finished(0, QProcess.ExitStatus.NormalExit)
                    self.assertEqual(window.targets.count(), 0)
                    calls = [json.loads(line) for line in log_path.read_text().splitlines()]
                    self.assertIn(["send", "--to", "ABC123", "--", str(file_path)], calls)
                finally:
                    window.close()


if __name__ == "__main__":
    unittest.main()
