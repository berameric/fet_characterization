"""
FET Characterization Tool Version Information
"""

__version__ = "1.0.0"
__author__ = "Bilal Bera Meriç"
__email__ = "b.berameric@gmail.com"
__description__ = "FET Characterization Tool with Keithley Instruments"
__url__ = "https://github.com/berameric/fet_characterization"

# Version history
VERSION_HISTORY = {
    "1.0.0": {
        "date": "2025-01-20",
        "features": [
            "Initial release",
            "Output and Transfer curve measurements",
            "Real-time plotting with PyQtGraph",
            "Keithley 2401 and 2635A support",
            "Demo mode with mock instruments",
            "CSV data export",
            "Mobility calculation feature",
            "Linear region analysis",
            "Multi-voltage measurement support"
        ],
        "bug_fixes": [],
        "breaking_changes": []
    }
}

def get_version():
    """Return the current version string."""
    return __version__

def get_version_info():
    """Return detailed version information."""
    return {
        "version": __version__,
        "author": __author__,
        "description": __description__,
        "url": __url__
    } 