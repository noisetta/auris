"""
compare.py — Auris Compare Files Dialog

Allows comparing 2–5 audio files side by side using the same
analysis engine as the main Auris scan. Produces a clear winner
recommendation based on quality, dynamic range, and technical specs.
"""

import os
from audio_quality import analyze_file

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QFrame,
)


# ---------------------------------------------------------------------------
# Quality ranking helpers
# ---------------------------------------------------------------------------

QUALITY_RANK = {
    "Full Spectrum": 3,
    "Reduced Spectrum": 2,
    "Limited Spectrum": 1,
    "scan_failed": 0,
}

RISK_RANK = {
    "low": 2,
    "moderate": 1,
    "high": 0,
}


def calculate_risk(max_volume, mean_volume):
    if max_volume is None or mean_volume is None:
        return "unknown"
    if max_volume >= -0.1 and mean_volume > -13:
        return "high"
    elif max_volume >= -0.5 and mean_volume > -15:
        return "moderate"
    else:
        return "low"


def determine_winner(results):
    """
    Rank files and determine the best one.
    Priority: Quality label > Dynamic Range > Sample Rate > Bit Depth
    Clipping risk is flagged as a warning but doesn't disqualify.

    Returns (winner_index, reasoning_list)
    """
    valid = [(i, r) for i, r in enumerate(results) if r.get("quality") != "scan_failed"]
    if not valid:
        return None, ["All files failed to scan."]
    if len(valid) == 1:
        return valid[0][0], ["Only one file scanned successfully."]

    # Score each file
    scores = []
    for i, r in valid:
        quality_score = QUALITY_RANK.get(r.get("quality", ""), 0)
        dr = r.get("dynamic_range") or 0
        sr = r.get("sample_rate") or 0
        bd = r.get("bit_depth") or 0
        scores.append((i, quality_score, dr, sr, bd, r))

    # Sort: quality desc, then DR desc, then SR desc, then BD desc
    scores.sort(key=lambda x: (x[1], x[2], x[3], x[4]), reverse=True)

    winner_idx = scores[0][0]
    winner = scores[0]
    reasoning = []

    # Explain the decision
    quality_values = set(s[1] for s in scores)
    if len(quality_values) > 1:
        reasoning.append(
            f"Quality label is decisive: {results[winner_idx].get('quality')} "
            f"outranks the other file(s)."
        )
    else:
        reasoning.append("All files share the same quality label.")

        dr_values = [s[2] for s in scores]
        if dr_values[0] != dr_values[1]:
            reasoning.append(
                f"Dynamic range is the tiebreaker: {winner[2]} dB "
                f"vs {scores[1][2]} dB. Higher dynamic range means "
                f"more natural, less compressed audio."
            )
        else:
            reasoning.append("Dynamic range is identical across files.")
            if scores[0][3] != scores[1][3]:
                reasoning.append(
                    f"Sample rate decides: {winner[3]} Hz vs {scores[1][3]} Hz."
                )
            elif scores[0][4] != scores[1][4]:
                reasoning.append(
                    f"Bit depth decides: {winner[4]}-bit vs {scores[1][4]}-bit."
                )
            else:
                reasoning.append("Files are technically identical — keep either.")

    # Clipping warnings
    for i, r in enumerate(results):
        risk = calculate_risk(r.get("max_volume"), r.get("mean_volume"))
        if risk == "high":
            name = os.path.basename(results[i].get("_path", f"File {i+1}"))
            reasoning.append(f"⚠ {name} has high clipping risk — may sound distorted at loud volumes.")

    return winner_idx, reasoning


# ---------------------------------------------------------------------------
# Analysis worker thread
# ---------------------------------------------------------------------------

class CompareWorker(QThread):
    progress = Signal(int, int, str)
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, file_paths):
        super().__init__()
        self.file_paths = file_paths

    def run(self):
        results = []
        total = len(self.file_paths)
        for i, path in enumerate(self.file_paths, 1):
            self.progress.emit(i, total, os.path.basename(path))
            try:
                result = analyze_file(path)
                result["_path"] = path
            except Exception as e:
                result = {
                    "_path": path,
                    "max_volume": None, "mean_volume": None,
                    "cutoff_freq": None, "quality": "scan_failed",
                    "dynamic_range": None, "sample_rate": None,
                    "bit_depth": None, "error": str(e),
                }
            results.append(result)
        self.finished.emit(results)


# ---------------------------------------------------------------------------
# Metric row widget
# ---------------------------------------------------------------------------

class MetricRow(QWidget):
    """A single labeled row in the comparison grid."""

    def __init__(self, label, values, highlight_best=True, higher_is_better=True, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)

        label_w = QLabel(label)
        label_w.setFixedWidth(130)
        label_w.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(label_w)

        # Find best value for highlighting
        numeric_values = []
        for v in values:
            try:
                numeric_values.append(float(v) if v not in (None, "", "—") else None)
            except (TypeError, ValueError):
                numeric_values.append(None)

        if highlight_best and any(v is not None for v in numeric_values):
            valid = [v for v in numeric_values if v is not None]
            best_val = max(valid) if higher_is_better else min(valid)
        else:
            best_val = None

        for i, (val, num_val) in enumerate(zip(values, numeric_values)):
            cell = QLabel(str(val) if val not in (None, "") else "—")
            cell.setAlignment(Qt.AlignCenter)
            cell.setMinimumWidth(160)
            cell.setStyleSheet("font-size: 13px; padding: 2px 8px;")

            if best_val is not None and num_val == best_val and len(valid) > 1:
                cell.setStyleSheet(
                    "font-size: 13px; padding: 2px 8px; "
                    "color: #4CAF50; font-weight: bold;"
                )
            layout.addWidget(cell)

        layout.addStretch()


# ---------------------------------------------------------------------------
# Main comparison dialog
# ---------------------------------------------------------------------------

class CompareDialog(QDialog):
    def __init__(self, parent=None, is_dark=False):
        super().__init__(parent)
        self.is_dark = is_dark
        self.file_paths = []
        self.results = []
        self.worker = None

        self.setWindowTitle("Auris — Compare Files")
        self.setMinimumWidth(820)
        self.setMinimumHeight(520)
        self.setModal(True)

        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(20, 20, 20, 20)

        # --- Header ---
        header = QLabel("Compare Files")
        header.setStyleSheet("font-size: 18px; font-weight: bold;")
        root.addWidget(header)

        sub = QLabel(
            "Select 2–5 audio files to compare their quality characteristics. "
            "EMMS will recommend which version to keep."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet("color: #888; font-size: 12px;")
        root.addWidget(sub)

        # --- File selection area ---
        self.file_list_layout = QVBoxLayout()
        self.file_list_layout.setSpacing(4)

        file_area_widget = QWidget()
        file_area_widget.setLayout(self.file_list_layout)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(file_area_widget)
        scroll.setMaximumHeight(130)
        scroll.setFrameShape(QFrame.NoFrame)
        root.addWidget(scroll)

        # File action buttons
        file_btn_row = QHBoxLayout()
        self.add_btn = QPushButton("+ Add Files")
        self.clear_btn = QPushButton("Clear All")
        self.clear_btn.setEnabled(False)
        file_btn_row.addWidget(self.add_btn)
        file_btn_row.addWidget(self.clear_btn)
        file_btn_row.addStretch()
        root.addLayout(file_btn_row)

        # --- Progress bar (hidden until scan starts) ---
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet("color: #888; font-size: 11px;")
        self.progress_label.setVisible(False)
        root.addWidget(self.progress_label)
        root.addWidget(self.progress_bar)

        # --- Results area (hidden until scan complete) ---
        self.results_widget = QWidget()
        self.results_layout = QVBoxLayout(self.results_widget)
        self.results_layout.setContentsMargins(0, 0, 0, 0)
        self.results_widget.setVisible(False)
        root.addWidget(self.results_widget)

        # --- Bottom buttons ---
        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setStyleSheet("color: #444;")
        root.addWidget(divider)

        btn_row = QHBoxLayout()
        self.compare_btn = QPushButton("Compare")
        self.compare_btn.setEnabled(False)
        self.compare_btn.setFixedHeight(34)
        self.compare_btn.setStyleSheet(
            "QPushButton { background: #4A90E2; color: white; border-radius: 4px; "
            "font-size: 13px; font-weight: bold; padding: 0 20px; } "
            "QPushButton:disabled { background: #555; color: #888; } "
            "QPushButton:hover:enabled { background: #5BA0F2; }"
        )
        close_btn = QPushButton("Close")
        close_btn.setFixedHeight(34)
        close_btn.clicked.connect(self.reject)

        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        btn_row.addWidget(self.compare_btn)
        root.addLayout(btn_row)

        # Connect signals
        self.add_btn.clicked.connect(self.add_files)
        self.clear_btn.clicked.connect(self.clear_files)
        self.compare_btn.clicked.connect(self.run_compare)

    def add_files(self):
        remaining = 5 - len(self.file_paths)
        if remaining <= 0:
            QMessageBox.information(self, "Limit reached", "Maximum 5 files can be compared at once.")
            return

        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select audio files to compare",
            os.path.expanduser("~/Music"),
            "Audio Files (*.flac *.mp3 *.wav *.m4a *.aac *.ogg *.opus)"
        )

        added = 0
        for path in paths:
            if path not in self.file_paths and len(self.file_paths) < 5:
                self.file_paths.append(path)
                self._add_file_row(path)
                added += 1

        self._refresh_buttons()

        # Clear previous results when files change
        if added > 0:
            self._clear_results()

    def _add_file_row(self, path):
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)

        icon = QLabel("♪")
        icon.setStyleSheet("color: #4A90E2; font-size: 14px;")
        icon.setFixedWidth(20)

        name = QLabel(os.path.basename(path))
        name.setStyleSheet("font-size: 12px;")

        folder = QLabel(os.path.dirname(path))
        folder.setStyleSheet("color: #666; font-size: 11px;")
        folder.setAlignment(Qt.AlignRight)

        remove_btn = QPushButton("✕")
        remove_btn.setFixedSize(22, 22)
        remove_btn.setStyleSheet(
            "QPushButton { color: #888; border: none; font-size: 11px; } "
            "QPushButton:hover { color: #e74c3c; }"
        )
        remove_btn.clicked.connect(lambda checked, p=path: self.remove_file(p))

        row.addWidget(icon)
        row.addWidget(name)
        row.addWidget(folder, stretch=1)
        row.addWidget(remove_btn)

        container = QWidget()
        container.setProperty("file_path", path)
        container.setLayout(row)
        self.file_list_layout.addWidget(container)

    def remove_file(self, path):
        if path in self.file_paths:
            self.file_paths.remove(path)

        # Remove the corresponding widget
        for i in range(self.file_list_layout.count()):
            item = self.file_list_layout.itemAt(i)
            if item and item.widget():
                w = item.widget()
                if w.property("file_path") == path:
                    w.setParent(None)
                    break

        self._refresh_buttons()
        self._clear_results()

    def clear_files(self):
        self.file_paths.clear()
        while self.file_list_layout.count():
            item = self.file_list_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        self._refresh_buttons()
        self._clear_results()

    def _refresh_buttons(self):
        count = len(self.file_paths)
        self.compare_btn.setEnabled(count >= 2)
        self.clear_btn.setEnabled(count > 0)
        self.add_btn.setEnabled(count < 5)

    def _clear_results(self):
        self.results_widget.setVisible(False)
        while self.results_layout.count():
            item = self.results_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        self.results = []

    def run_compare(self):
        if len(self.file_paths) < 2:
            return

        self._clear_results()
        self.compare_btn.setEnabled(False)
        self.add_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)

        self.progress_bar.setMaximum(len(self.file_paths))
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.progress_label.setVisible(True)

        self.worker = CompareWorker(self.file_paths)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _on_progress(self, current, total, filename):
        self.progress_bar.setValue(current)
        self.progress_label.setText(f"Analyzing: {filename}")

    def _on_finished(self, results):
        self.results = results
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        self.compare_btn.setEnabled(True)
        self.add_btn.setEnabled(len(self.file_paths) < 5)
        self.clear_btn.setEnabled(True)
        self._build_results(results)

    def _on_error(self, msg):
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        self.compare_btn.setEnabled(True)
        self.clear_btn.setEnabled(True)
        QMessageBox.critical(self, "Compare failed", msg)

    def _build_results(self, results):
        winner_idx, reasoning = determine_winner(results)

        # --- Column headers (filenames) ---
        header_row = QHBoxLayout()
        spacer = QLabel("")
        spacer.setFixedWidth(130)
        header_row.addWidget(spacer)

        for i, r in enumerate(results):
            name = os.path.basename(r.get("_path", f"File {i+1}"))
            # Truncate long names
            if len(name) > 28:
                name = name[:25] + "…"

            col_header = QLabel(name)
            col_header.setAlignment(Qt.AlignCenter)
            col_header.setMinimumWidth(160)
            col_header.setWordWrap(True)

            style = "font-size: 12px; font-weight: bold; padding: 4px 8px;"
            if i == winner_idx:
                style += " color: #4CAF50;"
            col_header.setStyleSheet(style)
            header_row.addWidget(col_header)

        header_row.addStretch()
        header_widget = QWidget()
        header_widget.setLayout(header_row)
        self.results_layout.addWidget(header_widget)

        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setStyleSheet("color: #444;")
        self.results_layout.addWidget(div)

        # --- Metric rows ---
        rows = [
            ("Quality", [r.get("quality", "—") for r in results], False, True),
            ("Dynamic Range", [r.get("dynamic_range") for r in results], True, True),
            ("True Peak", [r.get("true_peak") for r in results], True, False),
            ("Spectral Gap", [r.get("spectral_gap_db") for r in results], False, False),
            ("Sample Rate", [r.get("sample_rate") for r in results], True, True),
            ("Bit Depth", [r.get("bit_depth") for r in results], True, True),
            ("Max Volume", [r.get("max_volume") for r in results], True, False),
            ("Mean Volume", [r.get("mean_volume") for r in results], True, False),
        ]

        # Clipping risk row
        risk_values = [
            calculate_risk(r.get("max_volume"), r.get("mean_volume"))
            for r in results
        ]
        rows.append(("Clipping Risk", risk_values, False, False))

        for label, values, highlight, higher in rows:
            # For quality, use rank for comparison
            if label == "Quality":
                numeric_override = [QUALITY_RANK.get(str(v), 0) for v in values]
                row_w = MetricRow(label, values, highlight_best=highlight)
                # Override highlight manually
                self.results_layout.addWidget(row_w)
                continue

            if label == "Clipping Risk":
                # Highlight lowest risk in green
                risk_nums = [RISK_RANK.get(str(v), -1) for v in values]
                best = max(risk_nums) if risk_nums else -1
                row_layout = QHBoxLayout()
                row_layout.setContentsMargins(0, 2, 0, 2)
                lbl = QLabel(label)
                lbl.setFixedWidth(130)
                lbl.setStyleSheet("color: #888; font-size: 12px;")
                row_layout.addWidget(lbl)
                for v, num in zip(values, risk_nums):
                    cell = QLabel(str(v) if v else "—")
                    cell.setAlignment(Qt.AlignCenter)
                    cell.setMinimumWidth(160)
                    color = {"high": "#e74c3c", "moderate": "#e67e22", "low": "#4CAF50"}.get(str(v), "#888")
                    cell.setStyleSheet(f"font-size: 13px; padding: 2px 8px; color: {color};")
                    row_layout.addWidget(cell)
                row_layout.addStretch()
                rw = QWidget()
                rw.setLayout(row_layout)
                self.results_layout.addWidget(rw)
                continue

            row_w = MetricRow(label, values, highlight_best=highlight, higher_is_better=higher)
            self.results_layout.addWidget(row_w)

        # Divider
        div2 = QFrame()
        div2.setFrameShape(QFrame.HLine)
        div2.setStyleSheet("color: #444;")
        self.results_layout.addWidget(div2)

        # --- Winner banner ---
        winner_panel = QWidget()
        winner_panel.setStyleSheet(
            "background: rgba(76, 175, 80, 0.12); "
            "border: 1px solid rgba(76, 175, 80, 0.3); "
            "border-radius: 6px;"
        )
        winner_layout = QVBoxLayout(winner_panel)
        winner_layout.setContentsMargins(14, 10, 14, 10)
        winner_layout.setSpacing(4)

        if winner_idx is not None:
            winner_name = os.path.basename(results[winner_idx].get("_path", ""))
            title = QLabel(f"✓  Recommended: {winner_name}")
            title.setStyleSheet("font-size: 13px; font-weight: bold; color: #4CAF50;")
        else:
            title = QLabel("No clear winner could be determined.")
            title.setStyleSheet("font-size: 13px; color: #888;")

        winner_layout.addWidget(title)

        for reason in reasoning:
            r_label = QLabel(reason)
            r_label.setWordWrap(True)
            r_label.setStyleSheet("font-size: 11px; color: #aaa;")
            winner_layout.addWidget(r_label)

        self.results_layout.addWidget(winner_panel)
        self.results_widget.setVisible(True)

        # Resize dialog to fit results
        self.adjustSize()
        self.setMinimumHeight(self.height())
