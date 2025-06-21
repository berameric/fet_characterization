"""mock_controller.py
Standalone mock SMU to emulate drain or gate channels when hardware is absent.
"""
from __future__ import annotations
import math
import random

class MockSMU:
    """Simple mock model of a FET for demo purposes."""

    def __init__(self, role: str = "drain"):
        self.role = role
        self._voltage = 0.0

    # mimic hardware API
    def set_voltage(self, voltage: float):
        self._voltage = voltage

    def measure_current(self) -> float:
        # produce arbitrary I-V characteristic resembling a saturated MOSFET
        if self.role == "drain":
            Idss = 1e-3  # 1 mA peak current
            Vp = 2.0  # pinch-off
            current = Idss * max(0.0, (1 - self._voltage / Vp) ** 2)
        else:
            current = 0.0
        # Add some noise
        return current + 1e-5 * (random.random() - 0.5)

    def close(self):
        pass

    def set_nplc(self, nplc: float):
        pass 