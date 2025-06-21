"""measurement_worker.py
Background measurement thread performing nested drain/gate sweeps.
"""
from __future__ import annotations

import csv
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple, Union
import math

from PyQt5 import QtCore  # type: ignore

# Type alias for instrument drivers
DrainDriverT = object
GateDriverT = object


@dataclass
class SweepParameters:
    vd_start: float
    vd_stop: float
    vd_step: float
    vg_start: float
    vg_stop: float
    vg_step: float
    stabilization_s: float = 0.2
    repeats: int = 1
    csv_path: Union[str, Path] = Path("measurement.csv")
    separate_files: bool = False  # if True, one CSV per outer loop value
    outer_label: str = "Vg"  # label used in filename
    outer_first_gate: bool = True  # if True, outer loop is gate, else drain
    dwell_s: float = 0.05  # delay after setting drain before measurement
    nplc: float = 1.0


class MeasurementWorker(QtCore.QThread):
    """Runs the measurement loop in a separate thread."""

    data_ready = QtCore.pyqtSignal(float, float, float)  # Vg, Vd, Id
    progress = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()
    error = QtCore.pyqtSignal(str)
    set_started = QtCore.pyqtSignal(float, float)  # vg, vd

    def __init__(self, drain_driver: DrainDriverT, gate_driver: GateDriverT, params: SweepParameters):
        super().__init__()
        self.drain = drain_driver
        self.gate = gate_driver
        self.params = params
        self._running = True

        # configure NPLC if driver supports
        for drv in (self.drain, self.gate):
            if hasattr(drv, "set_nplc"):
                try:
                    drv.set_nplc(self.params.nplc)
                except Exception:
                    pass

    # --------------------------------------------------------------
    def stop(self):
        """Request a graceful stop."""
        self._running = False

    # --------------------------------------------------------------
    def run(self):
        # Prepare CSV
        csv_file = Path(self.params.csv_path).expanduser()
        csv_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with csv_file.open("w", newline="") as fp:
                writer = csv.writer(fp)
                writer.writerow(["Vg", "Vd", "Id (A)"])

                vg_values = self._frange(self.params.vg_start, self.params.vg_stop, self.params.vg_step)
                vd_values = self._frange(self.params.vd_start, self.params.vd_stop, self.params.vd_step)

                if self.params.outer_first_gate:
                    outer_vals, inner_vals = vg_values, vd_values
                    outer_is_gate = True
                else:
                    outer_vals, inner_vals = vd_values, vg_values
                    outer_is_gate = False

                total_points = len(outer_vals) * len(inner_vals) * self.params.repeats
                point_count = 0

                for _ in range(self.params.repeats):
                    for outer in outer_vals:
                        if not self._running:
                            raise RuntimeError("Measurement stopped by user")
                        if outer_is_gate:
                            self.gate.set_voltage(outer)
                        else:
                            self.drain.set_voltage(outer)
                        time.sleep(self.params.stabilization_s)

                        # open new file if separate_files True
                        if self.params.separate_files:
                            fp.close()
                            vlabel_val = outer
                            vlabel = f"{self.params.outer_label}_{vlabel_val:.2f}V".replace(".", "p")
                            csv_file = Path(self.params.csv_path)
                            stem = csv_file.stem
                            new_path = csv_file.parent / f"{stem}_{vlabel}{csv_file.suffix}"
                            fp = new_path.open("w", newline="")
                            writer = csv.writer(fp)
                            writer.writerow(["Vg", "Vd", "Id (A)"])

                        # notify new gate set started
                        if outer_is_gate:
                            self.set_started.emit(outer, math.nan)
                        else:
                            self.set_started.emit(math.nan, outer)

                        for inner in inner_vals:
                            if not self._running:
                                raise RuntimeError("Measurement stopped by user")
                            if outer_is_gate:
                                vd = inner
                                self.drain.set_voltage(vd)
                                vg_cur = outer
                            else:
                                vg_cur = inner
                                vd = outer
                                self.gate.set_voltage(vg_cur)
                            time.sleep(0.05)
                            time.sleep(self.params.dwell_s)
                            try:
                                id_val = self.drain.measure_current()
                            except Exception as e:
                                self.error.emit(f"Measurement error: {e}")
                                raise

                            self.data_ready.emit(vg_cur, vd, id_val)
                            writer.writerow([vg_cur, vd, id_val])
                            fp.flush()

                            point_count += 1
                            self.progress.emit(f"{point_count}/{total_points} points done")
        except Exception as exc:
            if not isinstance(exc, RuntimeError):
                self.error.emit(str(exc))
        finally:
            # Ensure outputs off
            try:
                self.drain.set_voltage(0)
                self.drain.close()
                self.gate.set_voltage(0)
                self.gate.close()
            except Exception:
                pass

            self.finished.emit()

    # --------------------------------------------------------------
    @staticmethod
    def _frange(start: float, stop: float, step: float):
        """Generate a floating-point range inclusive of endpoints."""
        num_steps = int(round((stop - start) / step))
        return [start + i * step for i in range(num_steps + 1)] 