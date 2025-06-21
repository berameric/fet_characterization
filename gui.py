"""gui.py
Main PyQt5 GUI for FET characterization tool.
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime
from typing import Optional
import math

from PyQt5 import QtWidgets, QtCore, QtGui

from keithley2401_controller import Keithley2401
from keithley2635a_controller import Keithley2635A
from mock_controller import MockSMU
from measurement_worker import MeasurementWorker, SweepParameters
from plotter import RealTimePlotter


# --------------------------------------------------------------
# Device configuration dialog
# --------------------------------------------------------------

class DeviceDialog(QtWidgets.QDialog):
    """Dialog to configure two devices and their VISA resources."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Connect Devices")

        layout = QtWidgets.QVBoxLayout(self)

        form = QtWidgets.QFormLayout()
        layout.addLayout(form)

        self.k2401_res_cb = QtWidgets.QComboBox()
        self.k2401_res_cb.setEditable(True)

        self.k2635_res_cb = QtWidgets.QComboBox()
        self.k2635_res_cb.setEditable(True)

        form.addRow("Keithley 2401 VISA", self.k2401_res_cb)
        form.addRow("Keithley 2635A VISA", self.k2635_res_cb)

        scan_btn = QtWidgets.QPushButton("Scan VISA")
        self.scan_btn = scan_btn
        self.scan_btn.clicked.connect(self._start_scan)
        layout.addWidget(self.scan_btn)

        btn_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

        # initial scan (non-blocking)
        self._start_scan()

    # ----------------------------------------------------------
    class _VisaScanner(QtCore.QThread):
        done = QtCore.pyqtSignal(list)

        def run(self):
            try:
                import pyvisa  # type: ignore
                rm = pyvisa.ResourceManager()
                # Use broad instrument pattern to avoid backend-specific slow searches
                resources = list(rm.list_resources('?*INSTR'))
            except Exception:
                resources = ["GPIB::24", "GPIB::25"]
            self.done.emit(resources)

    # ----------------------------------------------------------
    def _start_scan(self):
        self.scan_btn.setEnabled(False)
        self.scan_btn.setText("Scanning…")
        self._scanner = self._VisaScanner()
        self._scanner.done.connect(self._populate_resources)
        self._scanner.start()

    def _populate_resources(self, resources):
        # Update combos from background thread signal
        for cb in (self.k2401_res_cb, self.k2635_res_cb):
            current = cb.currentText()
            cb.blockSignals(True)
            cb.clear()
            cb.addItems(resources)
            cb.setCurrentIndex(-1)
            cb.blockSignals(False)
            if current:
                cb.setCurrentText(current)

        # re-enable scan button
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText("Scan VISA")

    # ----------------------------------------------------------
    def get_resources(self):
        """Return dict mapping model to resource string."""
        return {
            "2401": self.k2401_res_cb.currentText(),
            "2635A": self.k2635_res_cb.currentText(),
        }


# --------------------------------------------------------------
# Helper factory for spin boxes
# --------------------------------------------------------------

def _mk_dspin(default: float, minimum: float, maximum: float, step: float) -> QtWidgets.QDoubleSpinBox:
    sb = QtWidgets.QDoubleSpinBox()
    sb.setRange(minimum, maximum)
    sb.setDecimals(4)
    sb.setSingleStep(step)
    sb.setValue(default)
    # Keep spin boxes at a uniform width for cleaner alignment
    sb.setMaximumWidth(100)
    return sb


# --------------------------------------------------------------
# Tab widgets for different measurement modes
# --------------------------------------------------------------

class BaseTab(QtWidgets.QWidget):
    """Common functionality for Output & Transfer tabs."""

    def __init__(self, demo_checkbox: QtWidgets.QCheckBox, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.demo_checkbox = demo_checkbox  # reference to global checkbox

        # Horizontal main layout -> left panel (controls) + right (plot)
        hlayout = QtWidgets.QHBoxLayout(self)

        # ------------------------------------------------------------------
        # LEFT: control panel
        # ------------------------------------------------------------------
        self.control_panel = QtWidgets.QWidget()
        control_vlayout = QtWidgets.QVBoxLayout(self.control_panel)
        # Add some breathing room
        control_vlayout.setContentsMargins(8, 8, 8, 8)
        control_vlayout.setSpacing(10)

        # ------------------------------------------------------------------
        # Parameter group box (inputs)
        # ------------------------------------------------------------------
        self.backgate_cb = QtWidgets.QComboBox()

        self.params_group = QtWidgets.QGroupBox("Measurement Parameters")
        self.params_group.setStyleSheet(
            "QGroupBox { font-weight: bold; border: 1px solid gray; border-radius: 4px; margin-top: 6px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 3px 0 3px; }"
        )
        self.form_layout = QtWidgets.QFormLayout()
        self.form_layout.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        self.form_layout.addRow("Backgate device", self.backgate_cb)
        self.params_group.setLayout(self.form_layout)
        control_vlayout.addWidget(self.params_group)

        # ------------------------------------------------------------------
        # Run control group box (start/stop, progress)
        # ------------------------------------------------------------------
        self.run_group = QtWidgets.QGroupBox("Run Control")
        self.run_group.setStyleSheet(
            "QGroupBox { font-weight: bold; border: 1px solid gray; border-radius: 4px; margin-top: 6px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 3px 0 3px; }"
        )
        btn_layout = QtWidgets.QHBoxLayout()
        self.start_btn = QtWidgets.QPushButton("Start")
        self.stop_btn = QtWidgets.QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.stop_btn)
        self.progress_lbl = QtWidgets.QLabel("Idle")
        btn_layout.addWidget(self.progress_lbl)
        self.run_group.setLayout(btn_layout)
        control_vlayout.addWidget(self.run_group)

        # Push everything up and leave space at the bottom
        control_vlayout.addStretch()

        # Add left panel to layout
        hlayout.addWidget(self.control_panel, 0)

        # plotter will be defined by subclasses and added to hlayout by subclass
        self.plotter: Optional[RealTimePlotter] = None

        # Worker reference
        self.worker: Optional[MeasurementWorker] = None

        # Connect generic slots
        self.start_btn.clicked.connect(self._on_start_clicked)
        self.stop_btn.clicked.connect(self._on_stop_clicked)

    # ------------------------------------------------------------------
    def _on_start_clicked(self):
        if self.worker is not None:
            QtWidgets.QMessageBox.warning(self, "Busy", "Measurement already running in this tab.")
            return
        self.start_measurement()

    def _on_stop_clicked(self):
        if self.worker:
            self.worker.stop()

            self.stop_btn.setEnabled(False)
            self.progress_lbl.setText("Stopping…")

    # ------------------------------------------------------------------
    def _build_drivers(self):
        backgate_res = self.backgate_cb.currentText()
        mw: "MainWindow" = self.window()  # type: ignore
        return mw.create_drivers(backgate_res)

    # Called by MainWindow when device list updated
    def refresh_backgate_options(self, resources):
        self.backgate_cb.blockSignals(True)
        current = self.backgate_cb.currentText()
        self.backgate_cb.clear()
        self.backgate_cb.addItems(resources)
        if current in resources:
            self.backgate_cb.setCurrentText(current)
        elif resources:
            self.backgate_cb.setCurrentIndex(0)
        self.backgate_cb.blockSignals(False)

    # ------------------------------------------------------------------
    def _worker_finished(self):
        self.worker = None
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_lbl.setText("Finished")

    def _on_worker_error(self, msg: str):
        QtWidgets.QMessageBox.critical(self, "Measurement Error", msg)

    # ------------------------------------------------------------------
    # Abstract methods to be implemented by subclasses
    # ------------------------------------------------------------------
    def start_measurement(self):
        raise NotImplementedError


class OutputTab(BaseTab):
    """Nested drain sweep for each gate voltage."""

    def __init__(self, demo_checkbox: QtWidgets.QCheckBox, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(demo_checkbox, parent)

        # --- Parameter widgets specific to Output mode ---
        self.vd_start_sb = _mk_dspin(0.0, -100.0, 100.0, 0.1)
        self.vd_stop_sb = _mk_dspin(1.0, -100.0, 100.0, 0.1)
        self.vd_step_sb = _mk_dspin(0.1, 0.001, 100.0, 0.01)

        # Fixed or multiple gate voltages
        self.multi_cb = QtWidgets.QCheckBox("Multiple gate voltages")
        self.multi_cb.toggled.connect(self._update_mode)

        # Fixed value
        self.vg_fixed_sb = _mk_dspin(0.0, -40.0, 40.0, 0.1)

        # Sweep values for gate when multiple selected
        self.vg_start_sb = _mk_dspin(0.0, -40.0, 40.0, 0.1)
        self.vg_stop_sb = _mk_dspin(5.0, -40.0, 40.0, 0.1)
        self.vg_step_sb = _mk_dspin(0.5, 0.001, 40.0, 0.05)

        self.stab_time_sb = _mk_dspin(0.2, 0.0, 10.0, 0.1)
        self.repeats_sb = QtWidgets.QSpinBox()
        self.repeats_sb.setRange(1, 100)
        self.repeats_sb.setValue(1)

        # dwell per point
        self.dwell_sb = _mk_dspin(0.05, 0.0, 5.0, 0.01)

        self.form_layout.addRow(QtWidgets.QLabel("Drain Vd start [V]"), self.vd_start_sb)
        self.form_layout.addRow(QtWidgets.QLabel("Drain Vd stop [V]"), self.vd_stop_sb)
        self.form_layout.addRow(QtWidgets.QLabel("Drain Vd step [V]"), self.vd_step_sb)
        self.form_layout.addRow(self.multi_cb)
        self.form_layout.addRow(QtWidgets.QLabel("Gate Vg fixed [V]"), self.vg_fixed_sb)
        self.form_layout.addRow(QtWidgets.QLabel("Gate Vg start [V]"), self.vg_start_sb)
        self.form_layout.addRow(QtWidgets.QLabel("Gate Vg stop [V]"), self.vg_stop_sb)
        self.form_layout.addRow(QtWidgets.QLabel("Gate Vg step [V]"), self.vg_step_sb)
        self.form_layout.addRow(QtWidgets.QLabel("Stabilization [s]"), self.stab_time_sb)
        self.form_layout.addRow(QtWidgets.QLabel("Repeats"), self.repeats_sb)
        self.form_layout.addRow(QtWidgets.QLabel("Point dwell [s]"), self.dwell_sb)

        # --- Plotter ---
        self.plotter = RealTimePlotter(mode="output")
        self.layout().addWidget(self.plotter, 1)

        # initial mode
        self._update_mode(False)

    # ------------------------------------------------------------------
    def _update_mode(self, checked: bool):
        # Toggle visibility of fixed vs sweep widgets
        self.vg_fixed_sb.setVisible(not checked)
        for w in (self.vg_start_sb, self.vg_stop_sb, self.vg_step_sb):
            w.setVisible(checked)

    def start_measurement(self):
        if self.multi_cb.isChecked():
            vg_start = self.vg_start_sb.value()
            vg_stop = self.vg_stop_sb.value()
            vg_step = self.vg_step_sb.value()
            # compute total sets
            self._total_sets = int(round((vg_stop - vg_start) / vg_step)) + 1
        else:
            vg_start = vg_stop = self.vg_fixed_sb.value()
            vg_step = 1.0
            self._total_sets = 1
        self._current_set = 0

        outfile = self.window().get_output_dir() / self._default_csv_name("output")
        params = SweepParameters(
            vd_start=self.vd_start_sb.value(),
            vd_stop=self.vd_stop_sb.value(),
            vd_step=self.vd_step_sb.value(),
            vg_start=vg_start,
            vg_stop=vg_stop,
            vg_step=vg_step,
            stabilization_s=self.stab_time_sb.value(),
            repeats=self.repeats_sb.value(),
            separate_files=self.multi_cb.isChecked(),
            outer_label="Vg",
            outer_first_gate=True,
            csv_path=outfile,
            dwell_s=self.dwell_sb.value(),
            nplc=self.window().get_nplc(),
        )

        # always clear old measurement graph
        self.plotter.clear()

        try:
            drain, gate = self._build_drivers()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Driver Error", str(e))
            self.start_btn.setEnabled(True)
            return

        # Worker
        self.worker = MeasurementWorker(drain, gate, params)
        self.worker.data_ready.connect(self.plotter.add_point)
        self.worker.progress.connect(self._on_point_progress)
        self.worker.error.connect(self._on_worker_error)
        self.worker.set_started.connect(self._on_set_started)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_lbl.setText("Running…")

    # ------------------------------------------------------------------
    def _default_csv_name(self, suffix: str) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"fet_{suffix}_{ts}.csv"

    def _on_set_started(self, vg: float, vd: float):
        if not self.multi_cb.isChecked():
            return
        # Called once per outer gate value; vd is nan
        self._current_set += 1
        self.plotter.clear()    
        if math.isnan(vg):
            txt = f"Set {self._current_set}/{self._total_sets}  |  Vd={vd:.2f} V"
        else:
            txt = f"Set {self._current_set}/{self._total_sets}  |  Vg={vg:.2f} V"
        self.progress_lbl.setText(txt)

    def _on_point_progress(self, txt: str):
        if not self.multi_cb.isChecked():
            self.progress_lbl.setText(txt)


class TransferTab(BaseTab):
    """Gate sweep at fixed drain voltage."""

    def __init__(self, demo_checkbox: QtWidgets.QCheckBox, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(demo_checkbox, parent)

        # --- Parameters ---
        # Multiple drain voltages option
        self.multi_cb = QtWidgets.QCheckBox("Multiple drain voltages")
        self.multi_cb.toggled.connect(self._update_mode)

        self.vd_fixed_sb = _mk_dspin(1.0, -100.0, 100.0, 0.1)

        self.vd_start_sb = _mk_dspin(0.0, -100.0, 100.0, 0.1)
        self.vd_stop_sb = _mk_dspin(1.0, -100.0, 100.0, 0.1)
        self.vd_step_sb = _mk_dspin(0.1, 0.001, 100.0, 0.01)

        self.vg_start_sb = _mk_dspin(0.0, -40.0, 40.0, 0.1)
        self.vg_stop_sb = _mk_dspin(5.0, -40.0, 40.0, 0.1)
        self.vg_step_sb = _mk_dspin(0.1, 0.001, 40.0, 0.05)

        self.stab_time_sb = _mk_dspin(0.2, 0.0, 10.0, 0.1)
        self.repeats_sb = QtWidgets.QSpinBox()
        self.repeats_sb.setRange(1, 100)
        self.repeats_sb.setValue(1)

        # dwell per point
        self.dwell_sb = _mk_dspin(0.05, 0.0, 5.0, 0.01)

        self.form_layout.addRow(self.multi_cb)
        self.form_layout.addRow(QtWidgets.QLabel("Drain Vd fixed [V]"), self.vd_fixed_sb)
        self.form_layout.addRow(QtWidgets.QLabel("Drain Vd start [V]"), self.vd_start_sb)
        self.form_layout.addRow(QtWidgets.QLabel("Drain Vd stop [V]"), self.vd_stop_sb)
        self.form_layout.addRow(QtWidgets.QLabel("Drain Vd step [V]"), self.vd_step_sb)
        self.form_layout.addRow(QtWidgets.QLabel("Gate Vg start [V]"), self.vg_start_sb)
        self.form_layout.addRow(QtWidgets.QLabel("Gate Vg stop [V]"), self.vg_stop_sb)
        self.form_layout.addRow(QtWidgets.QLabel("Gate Vg step [V]"), self.vg_step_sb)
        self.form_layout.addRow(QtWidgets.QLabel("Stabilization [s]"), self.stab_time_sb)
        self.form_layout.addRow(QtWidgets.QLabel("Repeats"), self.repeats_sb)
        self.form_layout.addRow(QtWidgets.QLabel("Point dwell [s]"), self.dwell_sb)

        # --- Plotter ---
        self.plotter = RealTimePlotter(mode="transfer")
        self.layout().addWidget(self.plotter, 1)

        # initial mode
        self._update_mode(False)

    # ------------------------------------------------------------------
    def _update_mode(self, checked: bool):
        self.vd_fixed_sb.setVisible(not checked)
        for w in (self.vd_start_sb, self.vd_stop_sb, self.vd_step_sb):
            w.setVisible(checked)

    def start_measurement(self):
        if self.multi_cb.isChecked():
            vd_start = self.vd_start_sb.value()
            vd_stop = self.vd_stop_sb.value()
            vd_step = self.vd_step_sb.value()
            self._total_sets = int(round((vd_stop - vd_start) / vd_step)) + 1
        else:
            vd_start = vd_stop = self.vd_fixed_sb.value()
            vd_step = 1.0
            self._total_sets = 1
        self._current_set = 0

        outfile = self.window().get_output_dir() / self._default_csv_name("transfer")
        params = SweepParameters(
            vd_start=vd_start,
            vd_stop=vd_stop,
            vd_step=vd_step,
            vg_start=self.vg_start_sb.value(),
            vg_stop=self.vg_stop_sb.value(),
            vg_step=self.vg_step_sb.value(),
            stabilization_s=self.stab_time_sb.value(),
            repeats=self.repeats_sb.value(),
            separate_files=self.multi_cb.isChecked(),
            outer_label="Vd" if self.multi_cb.isChecked() else "Vg",
            outer_first_gate=not self.multi_cb.isChecked(),
            csv_path=outfile,
            dwell_s=self.dwell_sb.value(),
            nplc=self.window().get_nplc(),
        )

        # always clear old measurement graph
        self.plotter.clear()

        try:
            drain, gate = self._build_drivers()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Driver Error", str(e))
            self.start_btn.setEnabled(True)
            return

        # Worker
        self.worker = MeasurementWorker(drain, gate, params)
        self.worker.data_ready.connect(self.plotter.add_point)
        self.worker.progress.connect(self._on_point_progress)
        self.worker.error.connect(self._on_worker_error)
        self.worker.set_started.connect(self._on_set_started)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_lbl.setText("Running…")

    # ------------------------------------------------------------------
    def _default_csv_name(self, suffix: str) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"fet_{suffix}_{ts}.csv"

    def _on_set_started(self, vg: float, vd: float):
        if not self.multi_cb.isChecked():
            return
        # Called once per outer gate value; vd is nan
        self._current_set += 1
        self.plotter.clear()
        if math.isnan(vg):
            txt = f"Set {self._current_set}/{self._total_sets}  |  Vd={vd:.2f} V"
        else:
            txt = f"Set {self._current_set}/{self._total_sets}  |  Vg={vg:.2f} V"
        self.progress_lbl.setText(txt)

    def _on_point_progress(self, txt: str):
        if not self.multi_cb.isChecked():
            self.progress_lbl.setText(txt)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FET Characterization")
        self.resize(1100, 750)

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        vlayout = QtWidgets.QVBoxLayout(central)

        # Top bar widgets
        top_bar = QtWidgets.QHBoxLayout()
        self.demo_cb = QtWidgets.QCheckBox("Demo mode (no hardware)")
        self.demo_cb.setChecked(True)
        top_bar.addWidget(self.demo_cb)

        self.connect_btn = QtWidgets.QPushButton("Connect Devices…")
        self.connect_btn.clicked.connect(self._open_device_dialog)
        top_bar.addWidget(self.connect_btn)

        # Output directory selector
        self.output_dir_le = QtWidgets.QLineEdit(str(Path.cwd()))
        out_browse = QtWidgets.QPushButton("Output Folder…")
        out_browse.clicked.connect(self._browse_output_dir)
        top_bar.addWidget(self.output_dir_le)
        top_bar.addWidget(out_browse)

        # NPLC setting
        top_bar.addWidget(QtWidgets.QLabel("NPLC"))
        self.nplc_sb = QtWidgets.QDoubleSpinBox()
        self.nplc_sb.setDecimals(2)
        self.nplc_sb.setRange(0.01, 10.0)
        self.nplc_sb.setSingleStep(0.01)
        self.nplc_sb.setValue(1.00)
        self.nplc_sb.setMaximumWidth(80)
        top_bar.addWidget(self.nplc_sb)

        top_bar.addStretch()
        vlayout.addLayout(top_bar)

        # Tab widget
        tabs = QtWidgets.QTabWidget()
        self.output_tab = OutputTab(self.demo_cb)
        self.transfer_tab = TransferTab(self.demo_cb)
        tabs.addTab(self.output_tab, "Output Mode")
        tabs.addTab(self.transfer_tab, "Transfer Mode")
        vlayout.addWidget(tabs, 1)

        # Device configurations (model, resource)
        self.resource_map: dict[str, str] = {}
        self.device_resources: list[str] = []  # derived list

        # Initialize backgate dropdowns empty
        for tab in (self.output_tab, self.transfer_tab):
            tab.refresh_backgate_options([])

    # --------------------------------------------------------------
    def _open_device_dialog(self):
        dlg = DeviceDialog(self)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            self.resource_map = dlg.get_resources()
            self.device_resources = [v for v in self.resource_map.values() if v]
            resources = self.device_resources
            # Update tabs' backgate selectors
            for tab in (self.output_tab, self.transfer_tab):
                tab.refresh_backgate_options(resources)

    def create_drivers(self, backgate_res: str):
        """Instantiate driver objects based on stored configs and selected gate resource."""
        if self.demo_cb.isChecked() or not self.device_resources:
            return MockSMU("drain"), MockSMU("gate")

        gate_res = backgate_res or self.resource_map.get("2635A")
        drain_res = self.resource_map.get("2401") if gate_res == self.resource_map.get("2635A") else self.resource_map.get("2635A")

        # If any missing, default to first available
        if not drain_res:
            drain_res = next(iter(self.resource_map.values()))
        if not gate_res:
            gate_res = drain_res

        drain_driver = Keithley2401(resource_name=drain_res) if drain_res == self.resource_map.get("2401") else Keithley2635A(resource_name=drain_res)
        gate_driver = Keithley2401(resource_name=gate_res) if gate_res == self.resource_map.get("2401") else Keithley2635A(resource_name=gate_res)

        # apply NPLC
        nplc_val = self.get_nplc()
        for drv in (drain_driver, gate_driver):
            if hasattr(drv, "set_nplc"):
                try:
                    drv.set_nplc(nplc_val)
                except Exception:
                    pass

        return drain_driver, gate_driver

    # --------------------------------------------------------------
    def closeEvent(self, event):
        """Ensure any running measurement threads are stopped before exiting."""
        for tab in (self.output_tab, self.transfer_tab):
            if tab.worker is not None and tab.worker.isRunning():
                tab.worker.stop()
                tab.worker.wait(2000)  # wait up to 2 seconds
        event.accept()

    def _browse_output_dir(self):
        dir_path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Output Folder", str(Path.cwd()))
        if dir_path:
            self.output_dir_le.setText(dir_path)

    def get_output_dir(self) -> Path:
        return Path(self.output_dir_le.text()).expanduser().resolve()

    def get_nplc(self) -> float:
        return self.nplc_sb.value()


# ----------------------------------------------------------------------
# Convenience bootstrap
# ----------------------------------------------------------------------

def main():
    # High-DPI + Fusion theme + custom palette
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling)
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps)

    app = QtWidgets.QApplication(sys.argv)

    mw = MainWindow()
    mw.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main() 