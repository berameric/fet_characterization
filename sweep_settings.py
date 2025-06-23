"""sweep_settings.py
Advanced sweep settings and configurations for FET measurements.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from enum import Enum


class SweepMode(Enum):
    """Sweep direction and pattern options."""
    LINEAR = "linear"           # Normal linear sweep
    LOG = "logarithmic"        # Logarithmic spacing
    BIDIRECTIONAL = "bidirectional"  # Up then down
    CUSTOM = "custom"          # User-defined points


class ComplianceMode(Enum):
    """Current compliance handling."""
    ABORT = "abort"            # Stop measurement on compliance
    CONTINUE = "continue"      # Continue with next point
    SKIP = "skip"             # Skip compliant points


@dataclass
class AdvancedSweepSettings:
    """Advanced sweep configuration parameters."""
    
    # Timing settings
    stabilization_time: float = 0.2      # Time after gate voltage change
    point_dwell_time: float = 0.05       # Time after drain voltage change
    measurement_delay: float = 0.01      # Additional delay before measurement
    inter_sweep_delay: float = 0.5       # Delay between complete sweeps
    
    # Sweep behavior
    sweep_mode: SweepMode = SweepMode.LINEAR
    bidirectional_return: bool = True    # Return to start after sweep
    auto_zero: bool = True               # Auto-zero before each sweep
    
    # Compliance settings
    drain_compliance: float = 0.1        # Drain current compliance (A)
    gate_compliance: float = 1e-6        # Gate current compliance (A)
    compliance_mode: ComplianceMode = ComplianceMode.CONTINUE
    
    # Measurement averaging
    measurement_averages: int = 1        # Number of readings to average
    discard_first: bool = True           # Discard first reading (settling)
    
    # Source settling
    source_settling_time: float = 0.001  # Time for source to settle
    measure_settling_time: float = 0.001 # Time for measurement to settle
    
    # Advanced options
    use_4_wire: bool = False            # 4-wire measurement if supported
    filter_enabled: bool = True         # Digital filter on/off
    filter_count: int = 10              # Filter count
    
    # Safety limits
    max_voltage: float = 10.0           # Maximum allowed voltage
    max_current: float = 0.1            # Maximum allowed current
    temperature_check: bool = False     # Check instrument temperature
    
    def validate(self) -> list[str]:
        """Validate settings and return list of warnings/errors."""
        warnings = []
        
        if self.stabilization_time < 0:
            warnings.append("Stabilization time cannot be negative")
        
        if self.point_dwell_time < 0:
            warnings.append("Point dwell time cannot be negative")
            
        if self.drain_compliance <= 0:
            warnings.append("Drain compliance must be positive")
            
        if self.gate_compliance <= 0:
            warnings.append("Gate compliance must be positive")
            
        if self.measurement_averages < 1:
            warnings.append("Measurement averages must be at least 1")
            
        if self.filter_count < 1:
            warnings.append("Filter count must be at least 1")
            
        if self.max_voltage <= 0:
            warnings.append("Maximum voltage must be positive")
            
        if self.max_current <= 0:
            warnings.append("Maximum current must be positive")
            
        # Performance warnings
        if self.stabilization_time > 5.0:
            warnings.append("Long stabilization time may slow measurements significantly")
            
        if self.measurement_averages > 10:
            warnings.append("High averaging count will slow measurements")
            
        return warnings


@dataclass
class SweepProfile:
    """Predefined sweep profiles for different measurement types."""
    
    name: str
    description: str
    settings: AdvancedSweepSettings
    
    @classmethod
    def get_preset_profiles(cls) -> dict[str, 'SweepProfile']:
        """Get dictionary of preset sweep profiles."""
        profiles = {}
        
        # Fast measurement profile
        fast_settings = AdvancedSweepSettings(
            stabilization_time=0.05,
            point_dwell_time=0.01,
            measurement_delay=0.005,
            measurement_averages=1,
            filter_count=3
        )
        profiles["fast"] = cls(
            name="Fast Measurement",
            description="Quick measurements with minimal settling time",
            settings=fast_settings
        )
        
        # Precision measurement profile
        precision_settings = AdvancedSweepSettings(
            stabilization_time=0.5,
            point_dwell_time=0.1,
            measurement_delay=0.02,
            measurement_averages=5,
            filter_count=20,
            discard_first=True
        )
        profiles["precision"] = cls(
            name="Precision Measurement",
            description="High accuracy measurements with extended settling",
            settings=precision_settings
        )
        
        # Low noise profile
        low_noise_settings = AdvancedSweepSettings(
            stabilization_time=1.0,
            point_dwell_time=0.2,
            measurement_delay=0.05,
            measurement_averages=10,
            filter_count=50,
            auto_zero=True,
            discard_first=True
        )
        profiles["low_noise"] = cls(
            name="Low Noise",
            description="Maximum noise reduction for sensitive measurements",
            settings=low_noise_settings
        )
        
        # Default profile
        default_settings = AdvancedSweepSettings()
        profiles["default"] = cls(
            name="Default",
            description="Balanced speed and accuracy",
            settings=default_settings
        )
        
        return profiles


class SweepValidator:
    """Validates sweep parameters and suggests optimizations."""
    
    @staticmethod
    def validate_sweep_range(start: float, stop: float, step: float) -> dict:
        """Validate sweep range parameters."""
        result = {
            "valid": True,
            "warnings": [],
            "errors": [],
            "suggestions": []
        }
        
        # Basic validation
        if step <= 0:
            result["valid"] = False
            result["errors"].append("Step size must be positive")
            
        if abs(stop - start) < abs(step):
            result["warnings"].append("Step size larger than sweep range")
            
        # Calculate number of points
        if step > 0:
            num_points = int(abs(stop - start) / step) + 1
            if num_points > 1000:
                result["warnings"].append(f"Large number of points ({num_points}) may slow measurement")
            elif num_points < 5:
                result["warnings"].append(f"Few points ({num_points}) may give poor resolution")
                
        # Voltage range checks
        if abs(start) > 40 or abs(stop) > 40:
            result["warnings"].append("High voltages may damage devices")
            
        return result
    
    @staticmethod
    def estimate_measurement_time(settings: AdvancedSweepSettings, 
                                num_drain_points: int, 
                                num_gate_points: int) -> dict:
        """Estimate total measurement time."""
        
        # Time per point
        point_time = (settings.point_dwell_time + 
                     settings.measurement_delay + 
                     settings.source_settling_time)
        
        # Additional time for averaging
        if settings.measurement_averages > 1:
            point_time += settings.measurement_averages * 0.01
            
        # Time per sweep (one gate voltage)
        sweep_time = (settings.stabilization_time + 
                     num_drain_points * point_time)
        
        # Total time
        total_time = num_gate_points * sweep_time
        
        return {
            "point_time_s": point_time,
            "sweep_time_s": sweep_time,
            "total_time_s": total_time,
            "total_time_formatted": SweepValidator._format_time(total_time)
        }
    
    @staticmethod
    def _format_time(seconds: float) -> str:
        """Format time in human-readable format."""
        if seconds < 60:
            return f"{seconds:.1f} seconds"
        elif seconds < 3600:
            return f"{seconds/60:.1f} minutes"
        else:
            return f"{seconds/3600:.1f} hours" 