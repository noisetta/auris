import csv
import os
import subprocess
import sys
import scanner

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QAction, QPalette, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

CSV_OUTPUT = os.path.join(os.path.expanduser("~"), ".auris", "audio_scan_results.csv")
os.makedirs(os.path.dirname(CSV_OUTPUT), exist_ok=True)

class ScanWorker(QThread):
    progress = Signal(int, int, str)
    finished = Signal()
    error = Signal(str)

    def __init__(self, folder: str, output_csv: str) -> None:
        super().__init__()
        self.folder = folder
        self.output_csv = output_csv
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            scanner.scan_directory(
                self.folder,
                self.output_csv,
                progress_callback=self.on_progress,
                should_stop=lambda: self._stop
            )
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))

    def on_progress(self, current: int, total: int, file_path: str) -> None:
        if self._stop:
            raise InterruptedError("Scan stopped by user.")
        self.progress.emit(current, total, file_path)

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Auris")

        if getattr(sys, 'frozen', False):
            base_path = os.path.dirname(sys.executable)
            icon_path = os.path.join(base_path, "_internal", "auris.png")
        else:
            icon_path = os.path.join(os.path.dirname(__file__), "auris.png")

        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            QApplication.instance().setWindowIcon(QIcon(icon_path))
        
        self.resize(1200, 720)
        self.headers = []
        self.all_rows = []
        self.current_filter = "all"

        self.path_label = QLabel("Folder to scan:")
        self.path_edit = QLineEdit(os.path.expanduser("~/Music"))
        self.browse_button = QPushButton("Browse")
        self.scan_button = QPushButton("Scan")
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.export_button = QPushButton("Export CSV")
        self.help_button = QPushButton("?")
        self.help_button.setFixedWidth(30)
        self.help_button.setToolTip("Help")

        self.search_label = QLabel("Search:")
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Type to filter tracks, albums, artists, risk...")
        self.clear_search_button = QPushButton("Clear Search")

        self.status_label = QLabel("Ready.")

        self.filter_all = QPushButton("All")
        self.filter_high = QPushButton("High")
        self.filter_moderate = QPushButton("Moderate")
        self.filter_low = QPushButton("Low")
        self.filter_failed = QPushButton("Failed")

        self.filter_buttons = {
            "all": self.filter_all,
            "high": self.filter_high,
            "moderate": self.filter_moderate,
            "low": self.filter_low,
            "scan_failed": self.filter_failed,
        }

        self.open_button = QPushButton("Open File")
        self.reveal_button = QPushButton("Reveal in Folder")
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)

        self.table = QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels(["File", "Max Volume", "Mean Volume", "Risk", "Cutoff Freq", "Quality", "Dynamic Range", "Sample Rate", "Bit Depth"])
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)

        top_row = QHBoxLayout()
        top_row.addWidget(self.path_label)
        top_row.addWidget(self.path_edit)
        top_row.addWidget(self.browse_button)
        top_row.addWidget(self.scan_button)
        top_row.addWidget(self.stop_button)

        search_row = QHBoxLayout()
        search_row.addWidget(self.search_label)
        search_row.addWidget(self.search_edit)
        search_row.addWidget(self.clear_search_button)

        filter_row = QHBoxLayout()
        filter_row.addWidget(self.filter_all)
        filter_row.addWidget(self.filter_high)
        filter_row.addWidget(self.filter_moderate)
        filter_row.addWidget(self.filter_low)
        filter_row.addWidget(self.filter_failed)

        action_row = QHBoxLayout()
        action_row.addWidget(self.open_button)
        action_row.addWidget(self.reveal_button)
        action_row.addWidget(self.export_button)
        action_row.addStretch()
        action_row.addWidget(self.open_button)
        action_row.addWidget(self.reveal_button)
        action_row.addWidget(self.export_button)
        action_row.addStretch()
        action_row.addWidget(self.help_button)  

        layout = QVBoxLayout()
        layout.addLayout(top_row)
        layout.addWidget(self.status_label)
        layout.addLayout(search_row)
        layout.addLayout(filter_row)
        layout.addLayout(action_row)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.table)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.browse_button.clicked.connect(self.choose_folder)
        self.scan_button.clicked.connect(self.run_scan)
        self.stop_button.clicked.connect(self.stop_scan)
        self.export_button.clicked.connect(self.export_csv)
        self.help_button.clicked.connect(self.show_help)

        self.filter_all.clicked.connect(lambda: self.set_filter("all"))
        self.filter_high.clicked.connect(lambda: self.set_filter("high"))
        self.filter_moderate.clicked.connect(lambda: self.set_filter("moderate"))
        self.filter_low.clicked.connect(lambda: self.set_filter("low"))
        self.filter_failed.clicked.connect(lambda: self.set_filter("scan_failed"))

        self.search_edit.textChanged.connect(self.apply_filters)
        self.clear_search_button.clicked.connect(self.clear_search)

        self.table.itemDoubleClicked.connect(self.open_selected_file)
        self.table.customContextMenuRequested.connect(self.show_context_menu)

        self.open_button.clicked.connect(self.open_current_selection)
        self.reveal_button.clicked.connect(self.reveal_current_selection)

        self.update_filter_button_labels()
        self.update_filter_button_styles()

    def choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Select folder to scan", self.path_edit.text()
        )
        if folder:
            self.path_edit.setText(folder)

    def run_scan(self) -> None:
        folder = self.path_edit.text().strip()

        if not folder:
            QMessageBox.warning(self, "Missing folder", "Please choose a folder to scan.")
            return

        if not os.path.isdir(folder):
            QMessageBox.warning(self, "Invalid folder", f"This folder does not exist:\n{folder}")
            return

        self.status_label.setText("Scanning... this may take a while.")
        self.scan_button.setEnabled(False)
        self.browse_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)

        self.worker = ScanWorker(folder, CSV_OUTPUT)
        self.worker.progress.connect(self.on_scan_progress)
        self.worker.finished.connect(self.on_scan_finished)
        self.worker.error.connect(self.on_scan_error)
        self.worker.start()

    def stop_scan(self) -> None:
        if hasattr(self, "worker"):
            self.worker.stop()
        self.stop_button.setEnabled(False)
        self.status_label.setText("Stopping scan...")

    def on_scan_progress(self, current: int, total: int, file_path: str) -> None:
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.status_label.setText(f"Scanning {current}/{total}: {os.path.basename(file_path)}")

    def on_scan_finished(self) -> None:
        self.scan_button.setEnabled(True)
        self.browse_button.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.stop_button.setEnabled(False)

        if not os.path.isfile(CSV_OUTPUT):
            QMessageBox.critical(self, "Missing results", f"Expected CSV not found:\n{CSV_OUTPUT}")
            self.status_label.setText("No CSV output found.")
            return

        self.load_csv(CSV_OUTPUT)
        self.status_label.setText("Scan complete.")

    def on_scan_error(self, message: str) -> None:
        self.scan_button.setEnabled(True)
        self.browse_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.progress_bar.setVisible(False)
        QMessageBox.critical(self, "Scan error", message)
        self.status_label.setText("Scan failed.")
        if "Scan stopped by user" in message:
            self.status_label.setText("Scan stopped.")
            if os.path.isfile(CSV_OUTPUT):
                self.load_csv(CSV_OUTPUT)
        else:
            QMessageBox.critical(self, "Scan error", message)
            self.status_label.setText("Scan failed.")

    def load_csv(self, csv_path: str) -> None:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)

        if not rows:
            self.table.setRowCount(0)
            self.headers = []
            self.all_rows = []
            self.update_filter_button_labels()
            self.update_filter_button_styles()
            return

        self.headers = rows[0]
        self.all_rows = rows[1:]
        self.current_filter = "all"
        self.search_edit.clear()
        self.update_filter_button_labels()
        self.update_filter_button_styles()
        self.apply_filters()
    
    def get_row_color(self, risk_value: str) -> QColor | None:
        import platform
        palette = QApplication.palette()
        is_dark = palette.color(QPalette.Window).lightness() < 128
        is_linux = platform.system() == "Linux"

        if is_linux:
        # Solid colors for Fusion style
            colors = {
                "high": QColor("#5c2020") if is_dark else QColor("#ffcccc"),
                "moderate": QColor("#4a3c00") if is_dark else QColor("#fff4cc"),
                "low": QColor("#1a3d1a") if is_dark else QColor("#ccffcc"),
                "scan_failed": QColor("#3a3a3a") if is_dark else QColor("#e0e0e0"),
            }
        else:
        # Semi-transparent colors for Windows/macOS native themes
            colors = {
                "high": QColor(255, 80, 80, 60),
                "moderate": QColor(255, 200, 0, 60),
                "low": QColor(80, 200, 80, 60),
                "scan_failed": QColor(128, 128, 128, 60),
            }

        return colors.get(risk_value)

    def populate_table(self, data_rows) -> None:
        headers = self.headers

        self.table.setSortingEnabled(False)
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)

        tooltips = {
            "File": "The full path to the audio file on your system.",
            "Max Volume": "The loudest peak in the track (dBFS). Values close to 0.0 dB indicate potential clipping.",
            "Mean Volume": "The average loudness of the track (dBFS). Helps identify heavily compressed or quiet recordings.",
            "Risk": "Clipping risk based on peak and average volume. High = likely clipping, Moderate = borderline, Low = safe.",
            "Cutoff Freq": "Estimated frequency cutoff (Hz). 21000 = full lossless spectrum. 15000 = lossy source detected.",
            "Quality": "Overall quality estimate based on frequency content. Excellent = genuine lossless, Low quality lossy = likely transcoded from MP3.",
            "Dynamic Range": "The difference between the loudest and quietest parts (dB). Higher = more dynamic and natural sounding. Below 8 may indicate heavy compression.",
            "Sample Rate": "Number of audio samples per second (Hz). 44100 = CD quality. Higher rates capture more detail.",
            "Bit Depth": "Number of bits per sample. 16-bit = CD quality. 24-bit = studio quality with more dynamic headroom.",
        }

        for col_idx, header in enumerate(headers):
            if header in tooltips:
                self.table.horizontalHeaderItem(col_idx).setToolTip(tooltips[header])

        self.table.setRowCount(len(data_rows))

        for row_idx, row in enumerate(data_rows):
            risk_value = ""
            if "risk" in headers:
                risk_index = headers.index("risk")
                if risk_index < len(row):
                    risk_value = row[risk_index].strip().lower()

            row_color = self.get_row_color(risk_value)

            for col_idx, value in enumerate(row):
                clean_value = value.strip()
                item = QTableWidgetItem(clean_value)

                if headers[col_idx] in ("max_volume", "mean_volume"):
                    try:
                        item.setData(Qt.DisplayRole, float(clean_value))
                    except ValueError:
                        item.setText(clean_value)

                if row_color:
                    item.setBackground(row_color)

                self.table.setItem(row_idx, col_idx, item)

        self.table.resizeColumnsToContents()
        if len(headers) > 0:
            self.table.setColumnWidth(0, 620)
        self.table.setSortingEnabled(True)

    def update_filter_button_labels(self) -> None:
        counts = {
            "all": len(self.all_rows),
            "high": 0,
            "moderate": 0,
            "low": 0,
            "scan_failed": 0,
        }

        if self.headers and "risk" in self.headers:
            risk_index = self.headers.index("risk")
            for row in self.all_rows:
                if len(row) > risk_index:
                    risk_value = row[risk_index].strip().lower()
                    if risk_value in counts:
                        counts[risk_value] += 1

        self.filter_all.setText(f"All ({counts['all']})")
        self.filter_high.setText(f"High ({counts['high']})")
        self.filter_moderate.setText(f"Moderate ({counts['moderate']})")
        self.filter_low.setText(f"Low ({counts['low']})")
        self.filter_failed.setText(f"Failed ({counts['scan_failed']})")

    def update_filter_button_styles(self) -> None:
        default_style = ""
        active_style = """
            QPushButton {
                background-color: #4a90e2;
                color: white;
                font-weight: bold;
                border: 1px solid #2f5f99;
                padding: 6px;
                border-radius: 4px;
            }
        """

        for filter_name, button in self.filter_buttons.items():
            if filter_name == self.current_filter:
                button.setStyleSheet(active_style)
            else:
                button.setStyleSheet(default_style)

    def clear_search(self) -> None:
        self.search_edit.clear()

    def set_filter(self, level: str) -> None:
        self.current_filter = level
        self.update_filter_button_styles()
        self.apply_filters()

    def apply_filters(self) -> None:
        if not self.all_rows or not self.headers:
            self.table.setRowCount(0)
            self.status_label.setText("No data loaded.")
            return

        search_text = self.search_edit.text().strip().lower()

        if self.current_filter == "all":
            filtered = self.all_rows
        else:
            risk_index = self.headers.index("risk")
            filtered = [
                row
                for row in self.all_rows
                if len(row) > risk_index and row[risk_index].strip().lower() == self.current_filter
            ]

        if search_text:
            search_filtered = []
            for row in filtered:
                row_text = " ".join(cell.strip().lower() for cell in row)
                if search_text in row_text:
                    search_filtered.append(row)
            filtered = search_filtered

        self.populate_table(filtered)
        self.status_label.setText(
            f"Showing {len(filtered)} track(s) | Filter: {self.current_filter} | Search: {search_text or 'none'}"
        )

    def get_selected_file_path(self) -> str | None:
        selected_items = self.table.selectedItems()
        if not selected_items:
            return None

        row = selected_items[0].row()
        file_item = self.table.item(row, 0)

        if file_item is None:
            return None

        file_path = file_item.text().strip()
        if not file_path:
            return None

        return file_path

    def open_current_selection(self) -> None:
        file_path = self.get_selected_file_path()
        if not file_path:
            QMessageBox.warning(self, "Open file", "Please select a row first.")
            return
        self.open_file_path(file_path)

    def reveal_current_selection(self) -> None:
        file_path = self.get_selected_file_path()
        if not file_path:
            QMessageBox.warning(self, "Reveal in folder", "Please select a row first.")
            return
        self.reveal_file_path(file_path)

    def open_selected_file(self, item) -> None:
        row = item.row()
        file_item = self.table.item(row, 0)

        if file_item is None:
            QMessageBox.warning(self, "Open file", "Could not find file path in this row.")
            return

        file_path = file_item.text().strip()
        self.open_file_path(file_path)

    def open_file_path(self, file_path: str) -> None:
        if not file_path:
            QMessageBox.warning(self, "Open file", "This row does not contain a valid file path.")
            return

        if not os.path.exists(file_path):
            QMessageBox.warning(
                self,
                "File not found",
                f"This file does not exist:\n{file_path}",
            )
            return

        try:
            subprocess.Popen(["xdg-open", file_path])
        except Exception as e:
            QMessageBox.critical(
                self,
                "Open failed",
                f"Could not open file:\n{file_path}\n\nError: {e}",
            )

    def reveal_file_path(self, file_path: str) -> None:
        if not file_path:
            QMessageBox.warning(self, "Reveal in folder", "This row does not contain a valid file path.")
            return

        if not os.path.exists(file_path):
            QMessageBox.warning(
                self,
                "File not found",
                f"This file does not exist:\n{file_path}",
            )
            return

        folder_path = os.path.dirname(file_path)

        try:
            subprocess.Popen(["xdg-open", folder_path])
        except Exception as e:
            QMessageBox.critical(
                self,
                "Reveal failed",
                f"Could not open folder:\n{folder_path}\n\nError: {e}",
            )

    def copy_selected_path(self) -> None:
        file_path = self.get_selected_file_path()
        if not file_path:
            QMessageBox.warning(self, "Copy path", "Please select a row first.")
            return

        QApplication.clipboard().setText(file_path)
        self.status_label.setText(f"Copied path: {file_path}")

    def show_context_menu(self, position) -> None:
        item = self.table.itemAt(position)
        if item is None:
            return

        self.table.selectRow(item.row())

        menu = QMenu(self)

        open_action = QAction("Open File", self)
        reveal_action = QAction("Reveal in Folder", self)
        copy_path_action = QAction("Copy Path", self)

        open_action.triggered.connect(self.open_current_selection)
        reveal_action.triggered.connect(self.reveal_current_selection)
        copy_path_action.triggered.connect(self.copy_selected_path)

        menu.addAction(open_action)
        menu.addAction(reveal_action)
        menu.addSeparator()
        menu.addAction(copy_path_action)

        menu.exec(self.table.viewport().mapToGlobal(position))
    
    def show_help(self) -> None:
        help_text = """
    <h2>Auris — How to Read Your Results</h2>

    <h3>🔴 Clipping Risk</h3>
    <p>Clipping happens when audio is recorded or mastered too loud, causing distortion.
    <b>High</b> risk means the track is very loud and likely distorted at peaks.
    <b>Moderate</b> means it's borderline.
    <b>Low</b> means the track has healthy headroom.</p>

    <h3>📊 Dynamic Range</h3>
    <p>Dynamic range measures the difference between the loudest and quietest moments in a track.
    A higher number means more natural, dynamic sound — like a live performance.
    A low number (below 8 dB) often means the track has been heavily compressed to sound loud,
    which is common in modern pop and streaming masters. Audiophiles generally prefer DR values above 12.</p>

    <h3>🎵 Quality & Cutoff Frequency</h3>
    <p>This tells you whether a file is truly lossless or has been converted from a lossy source like MP3.
    <b>Excellent (21000 Hz)</b> — Full frequency spectrum detected. Genuine lossless file (e.g. a real FLAC or WAV).
    <b>Likely Lossy (18000 Hz)</b> — Frequency content drops off early. May have been converted from a lossy source.
    <b>Low Quality Lossy (15000 Hz)</b> — Clear signs of lossy encoding. Likely an MP3 or AAC transcoded to FLAC.</p>

    <p>⚠️ A file can be a FLAC but still sound like an MP3 if it was converted from one.
    This scanner helps you identify those "fake lossless" files in your library.</p>

    <h3>📐 Sample Rate & Bit Depth</h3>
    <p><b>Sample rate</b> (Hz) — How many audio snapshots are taken per second.
    44100 Hz is CD quality. 96000 Hz and above is hi-res audio.
    Higher sample rates capture more high-frequency detail.</p>

    <p><b>Bit depth</b> — How much volume information each snapshot contains.
    16-bit is CD quality. 24-bit is studio quality with more dynamic headroom and less noise.
    Most audiophile recordings are 24-bit.</p>

    <h3>💡 What Should I Do With This?</h3>
    <ul>
    <li>Files marked <b>Low Quality Lossy</b> in your FLAC library are likely transcoded — consider replacing them with genuine lossless versions.</li>
    <li>Files with <b>High</b> clipping risk may sound distorted at loud volumes.</li>
    <li>Low <b>dynamic range</b> doesn't mean a file is broken — it's a mastering choice — but it may affect your listening experience.</li>
    </ul>
    """

        dialog = QMessageBox(self)
        dialog.setWindowTitle("Auris — Help")
        dialog.setText(help_text)
        dialog.setTextFormat(Qt.RichText)
        dialog.setStandardButtons(QMessageBox.Ok)
        dialog.exec()

    def export_csv(self) -> None:
        if not self.all_rows:
            QMessageBox.warning(self, "Export CSV", "No results to export. Please run a scan first.")
            return

        destination, _ = QFileDialog.getSaveFileName(
        self,
        "Export CSV",
        os.path.expanduser("~/audio_scan_results.csv"),
        "CSV Files (*.csv)",
        )

        if not destination:
            return

        try:
            import shutil
            shutil.copy2(CSV_OUTPUT, destination)
            self.status_label.setText(f"Exported to: {destination}")
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))

def main() -> None:
    app = QApplication(sys.argv)

    import platform
    if platform.system() == "Linux":
        app.setStyle("Fusion")
        
        is_dark = False

        # Try dconf directly (works for Cosmic and others)
        try:
            import subprocess
            result = subprocess.run(
                ["dconf", "read", "/org/gnome/desktop/interface/color-scheme"],
                capture_output=True, text=True
            )
            is_dark = "dark" in result.stdout.lower()
        except Exception:
            pass

        # Try gsettings GNOME schema as fallback
        if not is_dark:
            try:
                result = subprocess.run(
                    ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                    capture_output=True, text=True
                )
                is_dark = "dark" in result.stdout.lower()
            except Exception:
                pass

        # Final fallback — palette lightness
        if not is_dark:
            is_dark = app.palette().color(QPalette.Window).lightness() < 128

        app.setProperty("is_dark", is_dark)

        if is_dark:
            dark_palette = QPalette()
            dark_palette.setColor(QPalette.Window, QColor(45, 45, 45))
            dark_palette.setColor(QPalette.WindowText, QColor(220, 220, 220))
            dark_palette.setColor(QPalette.Base, QColor(30, 30, 30))
            dark_palette.setColor(QPalette.AlternateBase, QColor(45, 45, 45))
            dark_palette.setColor(QPalette.ToolTipBase, QColor(45, 45, 45))
            dark_palette.setColor(QPalette.ToolTipText, QColor(220, 220, 220))
            dark_palette.setColor(QPalette.Text, QColor(220, 220, 220))
            dark_palette.setColor(QPalette.Button, QColor(55, 55, 55))
            dark_palette.setColor(QPalette.ButtonText, QColor(220, 220, 220))
            dark_palette.setColor(QPalette.BrightText, QColor(255, 255, 255))
            dark_palette.setColor(QPalette.Highlight, QColor(74, 144, 226))
            dark_palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
            dark_palette.setColor(QPalette.Link, QColor(74, 144, 226))
            dark_palette.setColor(QPalette.Disabled, QPalette.Text, QColor(120, 120, 120))
            dark_palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(120, 120, 120))
            app.setPalette(dark_palette)

    # Set app icon
    icon_path = os.path.join(os.path.dirname(__file__), "auris.png")
    if os.path.exists(icon_path):
        app.setDesktopFileName("auris")
        app.setWindowIcon(QIcon(icon_path))

    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()