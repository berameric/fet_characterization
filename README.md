# FET Characterization Tool

This application provides a modern PyQt5 GUI for real-time characterization of field-effect transistors using Keithley 2401  and Keithley 2635A  SourceMeter units.

## Features

* Non-blocking PyQt5 interface with live updating PyQtGraph plots.
* Nested drain-gate sweeps running inside a dedicated worker thread.
* Automatic CSV logging of all measurements (Vg, Vd, Id).
* Modular codebase (GUI, worker thread, plotter, device drivers).
* Demo mode with mock instruments for development on machines without hardware.

## Getting Started

```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
python main.py
```

If you do **not** have real instruments connected, start the application and enable **Demo Mode** before running a sweep.

## File Layout

```
main.py                      ── Application entry-point
│
├── gui.py                   ── Main window & parameter forms
├── measurement_worker.py    ── QThread performing sweeps & logging
├── plotter.py               ── Real-time plotting component
├── keithley2401_controller.py
├── keithley2635a_controller.py
├── mock_controller.py       ── Virtual SMU for demo mode
└── requirements.txt
```

## License
MIT 
