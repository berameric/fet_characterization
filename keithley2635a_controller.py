"""keithley2635a_controller.py
Minimal control wrapper for Keithley 2635A SourceMeter (gate bias).
Uses SCPI-compatible commands for simplicity.
"""
from __future__ import annotations

import time

try:
    import pyvisa  # type: ignore
except ImportError:
    pyvisa = None  # type: ignore


class Keithley2635A:
    """Gate-bias SMU for FET characterization."""

    def __init__(self, resource_name: str = "GPIB::25", *, timeout: int = 5000, demo: bool = False):
        self.demo = demo or pyvisa is None
        self._voltage = 0.0
        if self.demo:
            self.inst = None
            return

        rm = pyvisa.ResourceManager()
        self.inst = rm.open_resource(resource_name)
        self.inst.timeout = timeout
        self.reset()
        self.configure_source()
        self.output_on()

    # ------------------------------------------------------------------
    def write(self, cmd: str) -> None:
        if self.demo:
            return
        self.inst.write(cmd)

    def reset(self) -> None:
        self.write("*RST")
        time.sleep(0.1)

    def configure_source(self) -> None:
        # configure channel A as voltage source, current measure (simplified)
        self.write("smua.source.func = smua.OUTPUT_DCVOLTS")
        self.write("smua.source.rangev = 40")
        self.write("smua.source.limiti = 0.01")  # 10 mA compliance
        self.write("smua.measure.rangei = 0.01")
        self.write("smua.source.levelv = 0")

    def output_on(self) -> None:
        self.write("smua.source.output = smua.OUTPUT_ON")

    def output_off(self) -> None:
        self.write("smua.source.output = smua.OUTPUT_OFF")

    # ------------------------------------------------------------------
    def set_voltage(self, voltage: float) -> None:
        self._voltage = voltage
        if self.demo:
            return
        self.write(f"smua.source.levelv = {voltage}")

    def measure_current(self) -> float:
        """Read current on channel A (in Amperes)."""
        if self.demo:
            import math, random
            self._current = 1e-3 * math.tanh(self._voltage) + 1e-4 * (random.random() - 0.5)
            return self._current

        # Simple TSP script query for current
        try:
            self.write("print(smua.measure.i())")
            import pyvisa  # type: ignore
            resp = self.inst.read()
            self._current = float(resp)
        except Exception:
            self._current = float("nan")
        return self._current

    def close(self) -> None:
        if not self.demo and self.inst is not None:
            try:
                self.output_off()
            finally:
                self.inst.close()

    # --------------------------------------------------------------
    def set_nplc(self, nplc: float):
        if self.demo:
            return
        self.write(f"smua.measure.nplc = {nplc}") 