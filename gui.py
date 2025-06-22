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
import pyqtgraph as pg
import numpy as np
from scipy import stats
import sympy as sp
from pint import UnitRegistry

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


class MobilityCalculationDialog(QtWidgets.QDialog):
    """Dialog for calculating FET mobility using transconductance and device parameters."""
    
    def __init__(self, gm_value: float = None, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("FET Mobility Calculation")
        self.setModal(True)
        self.resize(500, 600)
        
        # Initialize unit registry
        self.ureg = UnitRegistry()
        self.Q_ = self.ureg.Quantity
        
        layout = QtWidgets.QVBoxLayout(self)
        
        # Info label
        info_label = QtWidgets.QLabel(
            "Calculate FET mobility using transconductance from linear fit.\n"
            "Formula: μ = (gm / (Cox × V_DS)) × (L / W)"
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        # Parameters form
        form_layout = QtWidgets.QFormLayout()
        
        # Transconductance (from fit)
        self.gm_sb = QtWidgets.QDoubleSpinBox()
        self.gm_sb.setDecimals(6)
        self.gm_sb.setRange(-1e6, 1e6)
        self.gm_sb.setSuffix(" S")
        if gm_value is not None:
            self.gm_sb.setValue(gm_value)
        
        # Drain-source voltage
        self.vds_sb = QtWidgets.QDoubleSpinBox()
        self.vds_sb.setDecimals(3)
        self.vds_sb.setRange(0.001, 1000)
        self.vds_sb.setValue(0.1)
        self.vds_sb.setSuffix(" V")
        
        # Channel length
        self.length_sb = QtWidgets.QDoubleSpinBox()
        self.length_sb.setDecimals(1)
        self.length_sb.setRange(0.1, 10000)
        self.length_sb.setValue(5.0)
        self.length_sb.setSuffix(" μm")
        
        # Channel width
        self.width_sb = QtWidgets.QDoubleSpinBox()
        self.width_sb.setDecimals(1)
        self.width_sb.setRange(0.1, 10000)
        self.width_sb.setValue(20.0)
        self.width_sb.setSuffix(" μm")
        
        # Oxide thickness
        self.tox_sb = QtWidgets.QDoubleSpinBox()
        self.tox_sb.setDecimals(1)
        self.tox_sb.setRange(1.0, 10000)
        self.tox_sb.setValue(300.0)
        self.tox_sb.setSuffix(" nm")
        
        # Relative permittivity
        self.eps_r_sb = QtWidgets.QDoubleSpinBox()
        self.eps_r_sb.setDecimals(2)
        self.eps_r_sb.setRange(1.0, 100.0)
        self.eps_r_sb.setValue(3.9)  # SiO2
        
        form_layout.addRow("Transconductance (gm):", self.gm_sb)
        form_layout.addRow("Drain-Source Voltage (V_DS):", self.vds_sb)
        form_layout.addRow("Channel Length (L):", self.length_sb)
        form_layout.addRow("Channel Width (W):", self.width_sb)
        form_layout.addRow("Oxide Thickness (t_ox):", self.tox_sb)
        form_layout.addRow("Relative Permittivity (ε_r):", self.eps_r_sb)
        
        layout.addLayout(form_layout)
        
        # Calculate button
        calc_btn = QtWidgets.QPushButton("Calculate Mobility")
        calc_btn.clicked.connect(self._calculate_mobility)
        layout.addWidget(calc_btn)
        
        # Results display
        self.results_text = QtWidgets.QTextEdit()
        self.results_text.setReadOnly(True)
        self.results_text.setMaximumHeight(200)
        layout.addWidget(self.results_text)
        
        # Close button
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
    
    def _calculate_mobility(self):
        """Calculate mobility using the provided parameters."""
        try:
            # Get parameters with units
            gm = self.Q_(self.gm_sb.value(), 'A / V')
            V_DS = self.Q_(self.vds_sb.value(), 'V')
            L = self.Q_(self.length_sb.value(), 'micrometer')
            W = self.Q_(self.width_sb.value(), 'micrometer')
            t_ox = self.Q_(self.tox_sb.value(), 'nanometer')
            eps_r = self.eps_r_sb.value()
            
            # Calculate mobility
            mobility = self._calculate_mobility_core(gm, V_DS, L, W, eps_r, t_ox)
            
            # Display results
            results = self._format_results(gm, V_DS, L, W, t_ox, eps_r, mobility)
            self.results_text.setPlainText(results)
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Calculation Error", f"Failed to calculate mobility:\n{str(e)}")
    
    def _calculate_mobility_core(self, gm, V_DS, L, W, eps_r, t_ox):
        """Core mobility calculation function."""
        # Constants
        eps_0 = self.Q_(8.854e-12, 'F / m')
        
        # Calculate Cox: Cox = eps_0 * eps_r / t_ox
        Cox = (eps_0 * eps_r) / t_ox
        Cox = Cox.to('F / meter ** 2')
        
        # Calculate mobility: μ = (gm / (Cox * V_DS)) * (L / W)
        mu_FE = (gm / (Cox * V_DS)) * (L / W)
        mu_FE = mu_FE.to('centimeter ** 2 / volt / second')
        
        return mu_FE, Cox
    
    def _format_results(self, gm, V_DS, L, W, t_ox, eps_r, mobility_data):
        """Format calculation results for display."""
        mu_FE, Cox = mobility_data
        
        results = f"""
Mobility Calculation Results

gₘ = {gm:.3e}
V_DS = {V_DS}
L = {L}
W = {W}

Result: μ_FE = {mu_FE:.1f}

Formula: μ = (gₘ/Cₒₓ⋅V_DS) × (L/W)
"""
        return results.strip()


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


class CalculationTab(QtWidgets.QWidget):
    """Tab for loading and visualizing CSV data files."""
    
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        
        # Horizontal main layout -> left panel (controls) + right (plot)
        hlayout = QtWidgets.QHBoxLayout(self)
        
        # ------------------------------------------------------------------
        # LEFT: control panel
        # ------------------------------------------------------------------
        self.control_panel = QtWidgets.QWidget()
        control_vlayout = QtWidgets.QVBoxLayout(self.control_panel)
        control_vlayout.setContentsMargins(8, 8, 8, 8)
        control_vlayout.setSpacing(10)
        
        # File selection group
        file_group = QtWidgets.QGroupBox("CSV File Selection")
        file_group.setStyleSheet(
            "QGroupBox { font-weight: bold; border: 1px solid gray; border-radius: 4px; margin-top: 6px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 3px 0 3px; }"
        )
        file_layout = QtWidgets.QVBoxLayout()
        
        # File path display and browse button
        self.file_path_le = QtWidgets.QLineEdit()
        self.file_path_le.setPlaceholderText("No file selected")
        self.file_path_le.setReadOnly(True)
        
        self.browse_btn = QtWidgets.QPushButton("Browse CSV File...")
        self.browse_btn.clicked.connect(self._browse_csv_file)
        
        self.load_btn = QtWidgets.QPushButton("Load File")
        self.load_btn.clicked.connect(self._load_csv_file)
        self.load_btn.setEnabled(False)
        
        file_layout.addWidget(self.file_path_le)
        file_layout.addWidget(self.browse_btn)
        file_layout.addWidget(self.load_btn)
        file_group.setLayout(file_layout)
        control_vlayout.addWidget(file_group)
        
        # Column selection group
        self.column_group = QtWidgets.QGroupBox("Column Selection")
        self.column_group.setStyleSheet(
            "QGroupBox { font-weight: bold; border: 1px solid gray; border-radius: 4px; margin-top: 6px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 3px 0 3px; }"
        )
        column_layout = QtWidgets.QFormLayout()
        
        self.x_column_cb = QtWidgets.QComboBox()
        self.y_column_cb = QtWidgets.QComboBox()
        self.group_column_cb = QtWidgets.QComboBox()
        self.group_column_cb.addItem("None (single curve)")
        
        # Auto-detect button
        self.auto_detect_btn = QtWidgets.QPushButton("Auto-detect FET")
        self.auto_detect_btn.clicked.connect(self._auto_detect_fet_columns)
        self.auto_detect_btn.setEnabled(False)
        
        # Plot button
        self.plot_btn = QtWidgets.QPushButton("Plot Data")
        self.plot_btn.clicked.connect(self._plot_data)
        self.plot_btn.setEnabled(False)
        
        column_layout.addRow("X-axis column:", self.x_column_cb)
        column_layout.addRow("Y-axis column:", self.y_column_cb)
        column_layout.addRow("Group by:", self.group_column_cb)
        column_layout.addRow("", self.auto_detect_btn)
        column_layout.addRow("", self.plot_btn)
        
        self.column_group.setLayout(column_layout)
        self.column_group.setEnabled(False)
        control_vlayout.addWidget(self.column_group)
        
        # Linear fitting group
        self.linear_group = QtWidgets.QGroupBox("Linear Region Analysis")
        self.linear_group.setStyleSheet(
            "QGroupBox { font-weight: bold; border: 1px solid gray; border-radius: 4px; margin-top: 6px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 3px 0 3px; }"
        )
        linear_layout = QtWidgets.QVBoxLayout()
        
        # Enable/disable linear region selection
        self.enable_linear_cb = QtWidgets.QCheckBox("Enable Linear Region Selection")
        self.enable_linear_cb.toggled.connect(self._toggle_linear_region)
        linear_layout.addWidget(self.enable_linear_cb)
        
        # Buttons for linear analysis
        btn_layout = QtWidgets.QHBoxLayout()
        self.fit_btn = QtWidgets.QPushButton("Fit Linear")
        self.fit_btn.clicked.connect(self._fit_linear_region)
        self.fit_btn.setEnabled(False)
        
        self.clear_fit_btn = QtWidgets.QPushButton("Clear Fit")
        self.clear_fit_btn.clicked.connect(self._clear_linear_fit)
        self.clear_fit_btn.setEnabled(False)
        
        # Mobility calculation button
        self.mobility_btn = QtWidgets.QPushButton("Calculate Mobility")
        self.mobility_btn.clicked.connect(self._open_mobility_dialog)
        self.mobility_btn.setEnabled(False)
        linear_layout.addWidget(self.mobility_btn)
        
        btn_layout.addWidget(self.fit_btn)
        btn_layout.addWidget(self.clear_fit_btn)
        linear_layout.addLayout(btn_layout)
        
        # Results display
        self.fit_results_label = QtWidgets.QLabel("No fit performed")
        self.fit_results_label.setWordWrap(True)
        self.fit_results_label.setStyleSheet("QLabel { background-color: #f0f0f0; color: #000000; padding: 5px; border: 1px solid #ccc; font-family: monospace; }")
        linear_layout.addWidget(self.fit_results_label)
        
        self.linear_group.setLayout(linear_layout)
        self.linear_group.setEnabled(False)
        control_vlayout.addWidget(self.linear_group)
        
        # Info group
        info_group = QtWidgets.QGroupBox("File Information")
        info_group.setStyleSheet(
            "QGroupBox { font-weight: bold; border: 1px solid gray; border-radius: 4px; margin-top: 6px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 3px 0 3px; }"
        )
        self.info_label = QtWidgets.QLabel("No file loaded")
        self.info_label.setWordWrap(True)
        info_layout = QtWidgets.QVBoxLayout()
        info_layout.addWidget(self.info_label)
        info_group.setLayout(info_layout)
        control_vlayout.addWidget(info_group)
        
        # Push everything up and leave space at the bottom
        control_vlayout.addStretch()
        
        # Set fixed width for control panel
        self.control_panel.setMaximumWidth(300)
        hlayout.addWidget(self.control_panel, 0)
        
        # ------------------------------------------------------------------
        # RIGHT: plot area
        # ------------------------------------------------------------------
        pg.setConfigOptions(antialias=True)
        
        self.plot_widget = pg.PlotWidget(title="CSV Data Visualization")
        self.plot_widget.setLabel("left", "Current", units="A")
        self.plot_widget.setLabel("bottom", "Voltage", units="V")
        self.plot_widget.showGrid(True, True)
        self.plot_widget.setBackground('k')  # Dark background
        hlayout.addWidget(self.plot_widget, 1)
        
        # Store loaded data
        self.loaded_data = None
        
        # Linear region selection
        self.linear_region = None
        self.fit_line = None
    
    def _browse_csv_file(self):
        """Open file dialog to select CSV file."""
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, 
            "Select CSV File", 
            str(Path.cwd()), 
            "CSV Files (*.csv);;All Files (*)"
        )
        if file_path:
            self.file_path_le.setText(file_path)
            self.load_btn.setEnabled(True)
    
    def _load_csv_file(self):
        """Load the selected CSV file and populate column selectors."""
        file_path = self.file_path_le.text()
        if not file_path or not Path(file_path).exists():
            QtWidgets.QMessageBox.warning(self, "Error", "Please select a valid CSV file.")
            return
        
        try:
            import pandas as pd
            
            # Load CSV data
            self.loaded_data = pd.read_csv(file_path)
            
            # Get column names
            columns = self.loaded_data.columns.tolist()
            numeric_cols = self.loaded_data.select_dtypes(include=['number']).columns.tolist()
            
            # Populate column selectors
            for cb in (self.x_column_cb, self.y_column_cb):
                cb.clear()
                cb.addItems(numeric_cols)
            
            # Populate group column selector
            self.group_column_cb.clear()
            self.group_column_cb.addItem("None (single curve)")
            self.group_column_cb.addItems(columns)
            
            # Set default selections if possible
            if len(numeric_cols) >= 2:
                self.x_column_cb.setCurrentText(numeric_cols[0])
                self.y_column_cb.setCurrentText(numeric_cols[1])
            
            # Enable column selection and buttons
            self.column_group.setEnabled(True)
            self.auto_detect_btn.setEnabled(True)
            self.plot_btn.setEnabled(True)
            
            # Update info label
            rows, cols = self.loaded_data.shape
            self.info_label.setText(f"File: {Path(file_path).name}\nRows: {rows}\nColumns: {cols}\nColumns: {', '.join(columns)}")
            
            # Auto-detect FET columns if available
            if all(col in columns for col in ['Vg', 'Vd', 'Id']):
                self._auto_detect_fet_columns()
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error Loading File", f"Failed to load CSV file:\n{str(e)}")
    
    def _auto_detect_fet_columns(self):
        """Auto-detect and set FET measurement columns."""
        if self.loaded_data is None:
            return
        
        columns = self.loaded_data.columns.tolist()
        
        # Set standard FET columns if available
        if 'Vd' in columns:
            self.x_column_cb.setCurrentText('Vd')
        elif 'Vg' in columns:
            self.x_column_cb.setCurrentText('Vg')
        
        if 'Id' in columns:
            self.y_column_cb.setCurrentText('Id')
        
        # Determine grouping based on data structure
        if all(col in columns for col in ['Vg', 'Vd', 'Id']):
            unique_vg = len(self.loaded_data['Vg'].unique())
            unique_vd = len(self.loaded_data['Vd'].unique())
            
            if unique_vg > unique_vd:
                # Transfer mode: group by Vd
                self.x_column_cb.setCurrentText('Vg')
                self.group_column_cb.setCurrentText('Vd')
            else:
                # Output mode: group by Vg
                self.x_column_cb.setCurrentText('Vd')
                self.group_column_cb.setCurrentText('Vg')
    
    def _plot_data(self):
        """Plot data using selected columns."""
        if self.loaded_data is None:
            QtWidgets.QMessageBox.warning(self, "Error", "No data loaded.")
            return
        
        x_col = self.x_column_cb.currentText()
        y_col = self.y_column_cb.currentText()
        group_col = self.group_column_cb.currentText()
        
        if not x_col or not y_col:
            QtWidgets.QMessageBox.warning(self, "Error", "Please select both X and Y columns.")
            return
        
        try:
            # Clear previous plot and linear fit
            self.plot_widget.clear()
            if self.fit_line is not None:
                self.fit_line = None
            if self.linear_region is not None:
                self.linear_region = None
            self.fit_results_label.setText("No fit performed")
            
            # Set axis labels
            self.plot_widget.setLabel("bottom", x_col)
            self.plot_widget.setLabel("left", y_col)
            
            if group_col == "None (single curve)" or group_col not in self.loaded_data.columns:
                # Single curve
                pen = pg.mkPen(color='b', width=2)
                self.plot_widget.plot(
                    self.loaded_data[x_col], self.loaded_data[y_col],
                    pen=pen, symbol='o', symbolSize=4
                )
            else:
                # Multiple curves grouped by selected column
                unique_groups = sorted(self.loaded_data[group_col].unique())
                colors = ['b', 'r', 'g', 'c', 'm', 'y', 'k']
                
                for i, group_val in enumerate(unique_groups):
                    subset = self.loaded_data[self.loaded_data[group_col] == group_val]
                    if not subset.empty:
                        color = colors[i % len(colors)]
                        pen = pg.mkPen(color=color, width=2)
                        self.plot_widget.plot(
                            subset[x_col], subset[y_col],
                            pen=pen, symbol='o', symbolSize=4,
                            name=f"{group_col}={group_val:.3g}"
                        )
            
            # Enable linear analysis group
            self.linear_group.setEnabled(True)
            
            # If linear region was enabled, re-enable it for the new plot
            if self.enable_linear_cb.isChecked():
                self.enable_linear_cb.setChecked(False)  # This will clear any existing region
                self.enable_linear_cb.setChecked(True)   # This will create a new region for the new data
                        
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error Plotting", f"Failed to plot data:\n{str(e)}")
    
    def _toggle_linear_region(self, checked: bool):
        """Enable/disable linear region selection on the plot."""
        if checked and self.loaded_data is not None:
            # Create linear region selector if it doesn't exist
            if self.linear_region is None:
                # Get data range for initial region
                x_col = self.x_column_cb.currentText()
                if x_col and x_col in self.loaded_data.columns:
                    x_data = self.loaded_data[x_col].values
                    x_min, x_max = x_data.min(), x_data.max()
                    region_start = x_min + 0.2 * (x_max - x_min)
                    region_end = x_min + 0.8 * (x_max - x_min)
                    
                    self.linear_region = pg.LinearRegionItem(values=[region_start, region_end])
                    self.linear_region.setZValue(10)  # Put region on top
                    self.plot_widget.addItem(self.linear_region)
                    
            self.fit_btn.setEnabled(True)
            self.clear_fit_btn.setEnabled(True)
            self.mobility_btn.setEnabled(True)
        else:
            # Remove linear region selector
            if self.linear_region is not None:
                self.plot_widget.removeItem(self.linear_region)
                self.linear_region = None
            self.fit_btn.setEnabled(False)
            self.clear_fit_btn.setEnabled(False)
            self.mobility_btn.setEnabled(False)
            self._clear_linear_fit()
    
    def _fit_linear_region(self):
        """Fit a linear line to the selected region."""
        if self.loaded_data is None:
            QtWidgets.QMessageBox.warning(self, "Error", "No data loaded.")
            return
        
        if self.linear_region is None:
            QtWidgets.QMessageBox.warning(self, "Error", "Please enable linear region selection first.")
            return
        
        x_col = self.x_column_cb.currentText()
        y_col = self.y_column_cb.currentText()
        
        if not x_col or not y_col:
            QtWidgets.QMessageBox.warning(self, "Error", "Please select both X and Y columns.")
            return
        
        try:
            # Get selected region bounds
            region_bounds = self.linear_region.getRegion()
            x_min, x_max = min(region_bounds), max(region_bounds)
            
            # Filter data to selected region
            x_data = self.loaded_data[x_col].values
            y_data = self.loaded_data[y_col].values
            
            # Create mask for data within region
            mask = (x_data >= x_min) & (x_data <= x_max)
            x_region = x_data[mask]
            y_region = y_data[mask]
            
            if len(x_region) < 2:
                QtWidgets.QMessageBox.warning(self, "Error", "Not enough data points in selected region.")
                return
            
            # Perform linear regression
            slope, intercept, r_value, p_value, std_err = stats.linregress(x_region, y_region)
            
            # Remove previous fit line if it exists
            if self.fit_line is not None:
                self.plot_widget.removeItem(self.fit_line)
            
            # Plot linear fit line
            x_fit = np.linspace(x_min, x_max, 100)
            y_fit = slope * x_fit + intercept
            self.fit_line = self.plot_widget.plot(x_fit, y_fit, pen=pg.mkPen(color='r', width=3, style=QtCore.Qt.DashLine))
            
            # Calculate FET-specific parameters
            threshold_voltage = -intercept / slope if slope != 0 else float('inf')
            transconductance = slope  # For Id vs Vg, slope is transconductance
            
            # Update results display
            results_text = (
                f"Linear Fit Results:\n"
                f"Slope (gm): {slope:.6e} S\n"
                f"Intercept: {intercept:.6e} A\n"
                f"Threshold Voltage (Vth): {threshold_voltage:.4f} V\n"
                f"Transconductance: {transconductance:.6e} S\n"
                f"R-squared: {r_value**2:.6f}\n"
                f"Correlation: {r_value:.6f}\n"
                f"P-value: {p_value:.6e}\n"
                f"Std Error: {std_err:.6e}\n"
                f"Region: [{x_min:.3f}, {x_max:.3f}] V\n"
                f"Points: {len(x_region)}"
            )
            self.fit_results_label.setText(results_text)
            
            # Enable mobility calculation button
            self.mobility_btn.setEnabled(True)
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error Fitting", f"Failed to fit linear region:\n{str(e)}")
    
    def _clear_linear_fit(self):
        """Clear the linear fit line and results."""
        if self.fit_line is not None:
            self.plot_widget.removeItem(self.fit_line)
            self.fit_line = None
        self.fit_results_label.setText("No fit performed")
        self.mobility_btn.setEnabled(False)

    def _open_mobility_dialog(self):
        """Open the mobility calculation dialog when linear fit results are available."""
        results_text = self.fit_results_label.text()
        if results_text != "No fit performed":
            try:
                # Extract transconductance value from fit results
                lines = results_text.split('\n')
                gm_line = [line for line in lines if 'Transconductance:' in line][0]
                gm_str = gm_line.split('Transconductance: ')[1].split(' S')[0]
                gm_value = float(gm_str)
                
                # Open mobility calculation dialog
                dlg = MobilityCalculationDialog(gm_value, self)
                dlg.exec_()
                
            except (IndexError, ValueError) as e:
                QtWidgets.QMessageBox.warning(self, "Error", f"Could not extract transconductance value: {str(e)}")
        else:
            QtWidgets.QMessageBox.warning(self, "No Fit Data", "Please perform a linear fit first.")
    
    def _open_mobility_calculation_dialog(self, gm_value: float):
        """Open the mobility calculation dialog with the given transconductance."""
        dlg = MobilityCalculationDialog(gm_value)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            # Handle the result of the mobility calculation dialog
            pass


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
        self.calculation_tab = CalculationTab()
        tabs.addTab(self.output_tab, "Output Mode")
        tabs.addTab(self.transfer_tab, "Transfer Mode")
        tabs.addTab(self.calculation_tab, "Calculation")
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