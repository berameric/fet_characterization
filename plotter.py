"""plotter.py
Real-time plotting widgets using PyQtGraph.
"""
from __future__ import annotations

from typing import Optional, Dict, List, Tuple

import pyqtgraph as pg  # type: ignore
from PyQt5 import QtWidgets  # type: ignore

pg.setConfigOptions(antialias=True)


class RealTimePlotter(QtWidgets.QWidget):
    """Single-plot widget for real-time Output or Transfer curves.

    Parameters
    ----------
    mode : str
        "output" for Id vs Vd (multiple curves for each Vg) or
        "transfer" for Id vs Vg (single curve).
    """

    def __init__(self, mode: str = "output", parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)

        if mode not in {"output", "transfer"}:
            raise ValueError("mode must be 'output' or 'transfer'")

        self.mode = mode

        self.plot = pg.PlotWidget(title=self._default_title())
        self.plot.setLabel("left", "Id", units="A")
        x_label = "Vd" if mode == "output" else "Vg"
        self.plot.setLabel("bottom", x_label, units="V")

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.plot)

        # Internal state
        self._output_curves: Dict[float, pg.PlotDataItem] = {}  # for output mode
        self._transfer_x: List[float] = []  # for transfer mode
        self._transfer_y: List[float] = []
        self._transfer_curve: Optional[pg.PlotDataItem] = None

    # ------------------------------------------------------------------
    def _default_title(self) -> str:
        return "Output Curve (Id vs Vd)" if self.mode == "output" else "Transfer Curve (Id vs Vg)"

    # ------------------------------------------------------------------
    def clear(self):
        """Clear plot and cached data."""
        self.plot.clear()
        self._output_curves.clear()
        self._transfer_x.clear()
        self._transfer_y.clear()
        self._transfer_curve = None

    # ------------------------------------------------------------------
    def add_point(self, vg: float, vd: float, id_val: float):
        """Add a new data point depending on the active mode."""
        if self.mode == "output":
            # Plot Id vs Vd, separate curve per Vg
            curve = self._output_curves.get(vg)
            if curve is None:
                pen = pg.mkPen(width=1)
                curve = self.plot.plot([], [], pen=pen, symbol='o', symbolSize=6, name=f"Vg={vg:.2f} V")
                self._output_curves[vg] = curve

            x, y = curve.getData()
            x = list(x) if x is not None else []
            y = list(y) if y is not None else []
            x.append(vd)
            y.append(id_val)
            curve.setData(x, y)
        else:  # transfer mode
            self._transfer_x.append(vg)
            self._transfer_y.append(id_val)
            if self._transfer_curve is None:
                pen = pg.mkPen(color="r", width=2)
                self._transfer_curve = self.plot.plot(self._transfer_x, self._transfer_y, pen=pen)
            else:
                self._transfer_curve.setData(self._transfer_x, self._transfer_y) 