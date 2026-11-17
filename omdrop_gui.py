#!/usr/bin/env python3
"""A small desktop front end for owly."""

import json
import re
import sys
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, Qt
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


RECEIVER_LINE = re.compile(r'^\s*(.*?)\s+("(?:\\.|[^"\\])*")\s+\((.+)\)\s*$')


def parse_receivers(output):
    receivers = []
    unrecognized = []
    for line in output.splitlines():
        if not line.strip():
            continue
        match = RECEIVER_LINE.match(line)
        if not match or not match.group(1).strip():
            unrecognized.append(line)
            continue
        instance, quoted_name, address = match.groups()
        try:
            name = json.loads(quoted_name)
        except json.JSONDecodeError:
            # Rust's debug strings can contain escapes that JSON does not support.
            name = quoted_name[1:-1]
        receivers.append((instance.strip(), name, address))
    return receivers, unrecognized


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Omdrop")
        self.resize(680, 600)
        self.file_path = None
        self.radio_ready = False
        self.radio_stopping = False
        self.radio_output = ""
        self.browse_output = ""
        self.send_output = ""

        self.radio = self.make_process()
        self.browse = self.make_process()
        self.send = self.make_process()
        self.radio.readyReadStandardError.connect(self.read_radio)
        self.radio.readyReadStandardOutput.connect(self.read_radio)
        self.radio.finished.connect(self.radio_finished)
        self.radio.errorOccurred.connect(lambda error: self.process_error("Radio", self.radio, error))
        self.browse.readyReadStandardOutput.connect(self.read_browse)
        self.browse.readyReadStandardError.connect(lambda: self.read_log(self.browse))
        self.browse.finished.connect(self.browse_finished)
        self.browse.errorOccurred.connect(lambda error: self.process_error("Discovery", self.browse, error))
        self.send.readyReadStandardOutput.connect(self.read_send)
        self.send.readyReadStandardError.connect(lambda: self.read_log(self.send))
        self.send.finished.connect(self.send_finished)
        self.send.errorOccurred.connect(lambda error: self.process_error("Transfer", self.send, error))

        root = QWidget()
        layout = QVBoxLayout(root)
        title = QLabel("Omdrop")
        title_font = title.font()
        title_font.setPointSize(20)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)
        subtitle = QLabel("Send a file to a nearby AirDrop device using Owly.")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        radio_row = QHBoxLayout()
        self.radio_button = QPushButton("Enable radio")
        self.radio_button.clicked.connect(self.toggle_radio)
        self.status = QLabel("Radio off")
        radio_row.addWidget(self.radio_button)
        radio_row.addWidget(self.status, 1)
        layout.addLayout(radio_row)

        hint = QLabel("On the receiving device, set AirDrop to Everyone for 10 minutes.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("Available devices"))
        target_row.addStretch()
        self.refresh_button = QPushButton("Find devices")
        self.refresh_button.clicked.connect(self.find_devices)
        target_row.addWidget(self.refresh_button)
        layout.addLayout(target_row)

        self.targets = QListWidget()
        self.targets.currentItemChanged.connect(self.update_controls)
        layout.addWidget(self.targets, 1)

        file_row = QHBoxLayout()
        self.file_button = QPushButton("Choose file")
        self.file_button.clicked.connect(self.choose_file)
        self.file_label = QLabel("No file selected")
        self.file_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        file_row.addWidget(self.file_button)
        file_row.addWidget(self.file_label, 1)
        layout.addLayout(file_row)

        self.send_button = QPushButton("Send file")
        self.send_button.clicked.connect(self.send_file)
        layout.addWidget(self.send_button)
        layout.addWidget(QLabel("Activity"))
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(160)
        layout.addWidget(self.log)
        self.setCentralWidget(root)
        self.update_controls()

    def make_process(self):
        process = QProcess(self)
        process.setProgram("owly")
        if getattr(sys, "frozen", False):
            environment = QProcessEnvironment.systemEnvironment()
            if environment.contains("LD_LIBRARY_PATH_ORIG"):
                environment.insert("LD_LIBRARY_PATH", environment.value("LD_LIBRARY_PATH_ORIG"))
            else:
                environment.remove("LD_LIBRARY_PATH")
            process.setProcessEnvironment(environment)
        return process

    def append_log(self, text):
        text = text.strip()
        if text:
            self.log.append(text)

    def read_log(self, process):
        self.append_log(bytes(process.readAllStandardError()).decode("utf-8", errors="replace"))

    def read_radio(self):
        text = bytes(self.radio.readAllStandardError()).decode("utf-8", errors="replace")
        text += bytes(self.radio.readAllStandardOutput()).decode("utf-8", errors="replace")
        self.radio_output += text
        self.append_log(text)
        if not self.radio_ready and re.search(r"\bawdl0 is up:", self.radio_output):
            self.radio_ready = True
            self.status.setText("Radio on")
            self.update_controls()

    def read_browse(self):
        self.browse_output += bytes(self.browse.readAllStandardOutput()).decode("utf-8", errors="replace")

    def read_send(self):
        self.send_output += bytes(self.send.readAllStandardOutput()).decode("utf-8", errors="replace")

    def process_error(self, label, process, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.append_log(f"{label} could not start: {process.errorString()}")
            if process is self.radio:
                self.status.setText("Radio off")
                self.radio_stopping = False
            self.update_controls()

    def toggle_radio(self):
        if self.radio.state() != QProcess.ProcessState.NotRunning:
            self.stop_radio()
            return
        answer = QMessageBox.warning(
            self,
            "Enable Owly radio?",
            "Depending on your Wi-Fi hardware, enabling the radio may temporarily disconnect Wi-Fi. "
            "Owly should restore it when the radio is disabled.",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Ok:
            return
        self.radio_output = ""
        self.radio_stopping = False
        self.status.setText("Starting radio…")
        self.radio.start("owly", ["radio", "up"])
        self.update_controls()

    def stop_radio(self):
        self.radio_stopping = True
        self.status.setText("Stopping radio…")
        for process in (self.browse, self.send):
            if process.state() != QProcess.ProcessState.NotRunning:
                process.kill()
        self.radio.terminate()
        self.update_controls()

    def radio_finished(self, exit_code, exit_status):
        self.read_radio()
        expected = self.radio_stopping and exit_code == 0 and exit_status == QProcess.ExitStatus.NormalExit
        self.radio_ready = False
        self.radio_stopping = False
        self.targets.clear()
        for process in (self.browse, self.send):
            if process.state() != QProcess.ProcessState.NotRunning:
                process.kill()
        self.status.setText("Radio off")
        if not expected:
            self.append_log(f"Radio stopped unexpectedly (exit code {exit_code}). Check activity or run owly doctor.")
        self.update_controls()

    def find_devices(self):
        self.targets.clear()
        self.browse_output = ""
        self.append_log("Looking for nearby devices for 10 seconds…")
        self.browse.start("owly", ["browse", "--seconds", "10"])
        self.update_controls()

    def browse_finished(self, exit_code, exit_status):
        self.read_browse()
        self.read_log(self.browse)
        receivers, unrecognized = parse_receivers(self.browse_output)
        if self.radio_ready and not self.radio_stopping:
            for instance, name, address in receivers:
                item = QListWidgetItem(f"{name}  ·  {instance}  ·  {address}")
                item.setData(Qt.ItemDataRole.UserRole, instance)
                self.targets.addItem(item)
        if unrecognized:
            self.append_log("Unrecognized discovery output:\n" + "\n".join(unrecognized))
        if exit_status != QProcess.ExitStatus.NormalExit or exit_code != 0:
            self.append_log(f"Discovery failed or was interrupted (exit code {exit_code}).")
        elif not receivers:
            self.append_log("No devices found. Check the receiver's AirDrop settings and try again.")
        else:
            self.append_log(f"Found {len(receivers)} device(s).")
        self.update_controls()

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose a file to send")
        if path:
            self.file_path = path
            self.file_label.setText(Path(path).name)
            self.file_label.setToolTip(path)
            self.update_controls()

    def send_file(self):
        target = self.targets.currentItem()
        if not target or not self.file_path:
            return
        if not Path(self.file_path).is_file():
            self.append_log("The selected file no longer exists or is not a regular file.")
            return
        self.send_output = ""
        self.append_log(f"Sending {Path(self.file_path).name} to {target.text()}…")
        self.send.start("owly", ["send", "--to", target.data(Qt.ItemDataRole.UserRole), "--", self.file_path])
        self.update_controls()

    def send_finished(self, exit_code, exit_status):
        self.read_send()
        self.read_log(self.send)
        self.append_log(self.send_output)
        if exit_status == QProcess.ExitStatus.NormalExit and exit_code == 0 and self.send_output.strip() == "delivered":
            self.append_log("Transfer complete.")
        else:
            self.append_log(f"Transfer failed or was interrupted (exit code {exit_code}).")
        self.update_controls()

    def update_controls(self, *_):
        radio_running = self.radio.state() != QProcess.ProcessState.NotRunning
        busy = any(p.state() != QProcess.ProcessState.NotRunning for p in (self.browse, self.send))
        ready = self.radio_ready and radio_running and not self.radio_stopping
        self.radio_button.setText("Disable radio" if radio_running else "Enable radio")
        self.radio_button.setEnabled(not self.radio_stopping)
        self.refresh_button.setEnabled(ready and not busy)
        self.file_button.setEnabled(not busy)
        self.targets.setEnabled(ready and not busy)
        self.send_button.setEnabled(ready and not busy and bool(self.targets.currentItem()) and bool(self.file_path))

    def closeEvent(self, event):
        for process in (self.browse, self.send):
            if process.state() != QProcess.ProcessState.NotRunning:
                process.kill()
                process.waitForFinished(3000)
        if self.radio.state() != QProcess.ProcessState.NotRunning:
            self.radio_stopping = True
            self.radio.terminate()
            if not self.radio.waitForFinished(10000):
                QMessageBox.warning(self, "Radio still stopping", "Owly has not released the radio yet. Please wait and try closing again.")
                event.ignore()
                return
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
