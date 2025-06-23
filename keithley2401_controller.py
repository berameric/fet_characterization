"""keithley2401_controller.py
Instrument driver for Keithley 2401 SourceMeter.
Uses PyVISA for communication.
"""
from __future__ import annotations

import time
from typing import Optional

try:
    import pyvisa  # type: ignore
except ImportError:  # graceful degradation if PyVISA is unavailable
    pyvisa = None  # type: ignore


class Keithley2401:
    """Minimal SCPI wrapper for the Keithley 2401.

    Parameters
    ----------
    resource_name : str
        VISA resource string, e.g. ``"GPIB::24"`` or ``"USB0::0x05E6::0x2401::123456::INSTR"``.
    timeout : int, optional
        Communication timeout in milliseconds.
    demo : bool, default False
        If *True*, no actual I/O is performed – useful for UI testing without hardware.
    """

    def __init__(self, resource_name: str = "GPIB::24", *, timeout: int = 5000, demo: bool = False):
        self.demo = demo or pyvisa is None
        self._voltage = 0.0  # cached last set voltage
        self._current = 0.0

        if self.demo:
            # Skip hardware initialisation
            self.inst = None
            return

        # Real instrument path
        rm = pyvisa.ResourceManager()
        self.inst = rm.open_resource(resource_name)
        self.inst.timeout = timeout
        self.reset()
        self.configure_source()
        self.output_on()

    # ---------------------------------------------------------------------
    # Basic SCPI helpers
    # ---------------------------------------------------------------------
    def write(self, cmd: str) -> None:
        if self.demo:
            return  # no-op in demo mode
        self.inst.write(cmd)

    def query(self, cmd: str) -> str:
        if self.demo:
            return "0"
        return self.inst.query(cmd)

    # ------------------------------------------------------------------
    def reset(self) -> None:
        self.write("*RST")
        time.sleep(0.1)

    def configure_source(self) -> None:
        """Set up instrument for voltage sourcing & current measurement."""
        self.write(":SOUR:FUNC VOLT")
        self.write(":SOUR:VOLT:RANG 20")  # 20 V full range
        self.write(":SENS:FUNC 'CURR'")
        self.write(":SENS:CURR:PROT 0.1")  # 100 mA compliance
        self.write(":FORM:ELEM CURR")

    def output_on(self) -> None:
        self.write(":OUTP ON")

    def output_off(self) -> None:
        self.write(":OUTP OFF")

    def set_compliance(self, compliance: float) -> None:
        """Set current compliance limit (in Amperes)."""
        if self.demo:
            return
        self.write(f":SENS:CURR:PROT {compliance}")

    # ------------------------------------------------------------------
    # Public API used by measurement thread
    # ------------------------------------------------------------------
    def set_voltage(self, voltage: float) -> None:
        """Source the specified drain voltage (in Volts)."""
        self._voltage = voltage
        if self.demo:
            return
        self.write(f":SOUR:VOLT {voltage}")

    def measure_current(self) -> float:
        """Trigger and fetch current measurement (in Amperes)."""
        if self.demo:
            # simple I-V characteristic approximation for demo
            import math, random

            self._current = 1e-3 * math.tanh(self._voltage) + 1e-4 * (random.random() - 0.5)
            return self._current

        resp = self.query(":READ?")
        try:
            self._current = float(resp)
        except ValueError:
            self._current = float("nan")
        return self._current

    def set_nplc(self, nplc: float):
        """Set integration time in power line cycles."""
        if self.demo:
            return
        self.write(f":SENS:CURR:NPLC {nplc}")

    # ------------------------------------------------------------------
    def close(self) -> None:
        if not self.demo and self.inst is not None:
            try:
                self.output_off()
            finally:
                self.inst.close() 