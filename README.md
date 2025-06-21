# FET Characterization Tool

A comprehensive PyQt5-based application for real-time characterization and analysis of field-effect transistors using Keithley 2401 (drain/source) and Keithley 2635A (back-gate) SourceMeter units.

## Features

### **Measurement Capabilities**
* **Output Curves**: Id vs Vd measurements with multiple gate voltages
* **Transfer Curves**: Id vs Vg measurements at fixed drain voltages
* **Multiple Measurement Modes**: Single measurements or multiple parameter sweeps
* **Real-time Plotting**: Live updating PyQtGraph plots with dark theme
* **Automatic CSV Logging**: Comprehensive data logging with timestamps

### **Advanced Analysis Tools**
* **Calculation Tab**: Load and visualize any CSV measurement data
* **Interactive Linear Region Selection**: Drag-and-drop region selection for linear fitting
* **FET Parameter Extraction**: Automatic calculation of threshold voltage and transconductance
* **Flexible Column Selection**: Choose any CSV columns for X/Y plotting
* **Multi-curve Visualization**: Group data by parameters for family curves

### **User Interface**
* **Modern Dark Theme**: Professional appearance with grid lines
* **Non-blocking Interface**: Measurements run in separate threads
* **Device Configuration**: Easy VISA resource scanning and selection
* **Progress Tracking**: Real-time voltage display and measurement progress
* **Error Handling**: User-friendly error messages and validation

### **Hardware Support**
* **Keithley 2401**: Primary drain/source measurement unit
* **Keithley 2635A**: Back-gate bias control
* **Demo Mode**: Mock instruments for development without hardware
* **Flexible Configuration**: Support for different instrument combinations

## Getting Started

### Installation
```bash
# Clone or download the repository
cd fet_characterization

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# Install dependencies
pip install -r requirements.txt

# Run the application
python main.py
```

### First Time Setup
1. **Demo Mode**: Enable "Demo mode" checkbox for testing without hardware
2. **Connect Devices**: Click "Connect Devices..." to configure VISA resources
3. **Output Directory**: Set your preferred data output folder
4. **NPLC Setting**: Adjust integration time for measurement speed vs. noise

## Usage Guide

### **Output Mode Tab**
- Configure drain voltage sweep parameters (start, stop, step)
- Set gate voltage values (single or multiple)
- Choose measurement timing (dwell time, stabilization)
- Real-time Id vs Vd curves with different colors for each Vg

### **Transfer Mode Tab**
- Configure gate voltage sweep parameters
- Set drain voltage values (single or multiple)
- Real-time Id vs Vg curves showing transfer characteristics
- Ideal for threshold voltage and transconductance analysis

### **Calculation Tab**
1. **Load CSV Data**: Browse and select measurement files
2. **Column Selection**: Choose X-axis, Y-axis, and grouping columns
3. **Auto-detect FET**: Automatically configure for standard FET data
4. **Linear Analysis**: 
   - Enable "Linear Region Selection"
   - Drag region boundaries to select linear portion
   - Click "Fit Linear" for automatic parameter extraction
   - View threshold voltage, transconductance, and fit statistics

## Key Features in Detail

### **Linear Region Analysis**
- **Interactive Selection**: Drag-and-drop region boundaries on plots
- **Statistical Analysis**: R-squared, correlation, p-value, standard error
- **FET Parameters**: Automatic calculation of Vth and gm
- **Visual Feedback**: Red dashed line showing linear fit
- **Comprehensive Results**: Detailed parameter display with proper units

### **Data Management**
- **Flexible CSV Export**: Single files or separate files per measurement set
- **Timestamp Naming**: Automatic file naming with date/time stamps
- **User-selectable Directories**: Choose output location for organized data
- **Multiple Formats**: Support for various CSV column arrangements

### **Measurement Control**
- **Speed Control**: Adjustable point dwell time and stabilization delays
- **Progress Monitoring**: Real-time voltage display and set counting
- **Safe Operation**: Proper instrument initialization and error handling
- **Interrupt Capability**: Stop measurements safely at any time

## File Structure

```
fet_characterization/
├── main.py                      ── Application entry point
├── gui.py                       ── Main window with three tabs
├── measurement_worker.py        ── Background measurement thread
├── plotter.py                   ── Real-time plotting with dark theme
├── keithley2401_controller.py   ── Keithley 2401 SCPI driver
├── keithley2635a_controller.py  ── Keithley 2635A TSP driver
├── mock_controller.py           ── Virtual instruments for demo
├── requirements.txt             ── Python dependencies
└── README.md                    ── This documentation
```

## Dependencies

- **PyQt5**: Modern GUI framework
- **PyQtGraph**: High-performance plotting
- **PyVISA**: Instrument communication
- **NumPy**: Numerical computations
- **Pandas**: Data manipulation and CSV handling
- **SciPy**: Statistical analysis and linear fitting

## Tips for Best Results

### **Measurement Setup**
- Use appropriate NPLC values (higher for low noise, lower for speed)
- Allow sufficient stabilization time for gate voltage changes
- Choose appropriate voltage ranges for your device characteristics

### **Linear Analysis**
- Select the most linear portion of your transfer curves
- Ensure sufficient data points in the selected region
- Check R-squared values to validate fit quality
- Use transconductance values to compare device performance

### **Data Organization**
- Use descriptive output directory names
- Enable separate files for multiple measurements when needed
- Keep measurement parameters consistent for comparative analysis

## Troubleshooting

- **VISA Errors**: Ensure instruments are properly connected and powered
- **Demo Mode**: Use for testing interface without hardware
- **CSV Loading**: Check file format and column names
- **Linear Fitting**: Ensure selected region contains sufficient data points

## License

This project is provided as-is for educational and research purposes.

