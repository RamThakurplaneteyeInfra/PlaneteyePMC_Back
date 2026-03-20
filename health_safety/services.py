# Health & Safety Service Layer
# Contains all business logic for pyramid model calculations

from typing import Dict, List, Any, Optional
from dataclasses import dataclass


# ============================================================================
# CONFIGURATION - Threshold values for safety status determination
# ============================================================================

class SafetyThresholds:
    """Configuration thresholds for safety status determination"""
    
    # Significant incidents threshold
    SIGNIFICANT_THRESHOLD = 2
    
    # Incident rate threshold (per 1,000,000 manhours)
    # Above this value, status becomes "moderate"
    INCIDENT_RATE_THRESHOLD = 50.0
    
    # High near miss threshold for alert flag
    HIGH_NEAR_MISS_THRESHOLD = 10
    
    # Maximum possible severity score (for normalization)
    MAX_SEVERITY_SCORE = 1000


# ============================================================================
# SEVERITY WEIGHTS
# ============================================================================

SEVERITY_WEIGHTS = {
    'fatalities': 5,
    'significant': 4,
    'major': 3,
    'minor': 2,
    'near_miss': 1,
}

# Reverse mapping for display
SEVERITY_LABELS = {
    'fatalities': 'Fatalities',
    'significant': 'Significant',
    'major': 'Major',
    'minor': 'Minor',
    'near_miss': 'Near Miss',
}

# Pyramid colors
PYRAMID_COLORS = {
    'fatalities': '#000000',    # Black
    'significant': '#FF0000',   # Red
    'major': '#FFA500',         # Orange
    'minor': '#FFFF00',         # Yellow
    'near_miss': '#00FF00',     # Green
}


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class HealthSafetyInput:
    """Input data structure for health & safety calculations"""
    total_manhours: float
    fatalities: int = 0
    significant: int = 0
    major: int = 0
    minor: int = 0
    near_miss: int = 0
    
    @property
    def total_incidents(self) -> int:
        return self.fatalities + self.significant + self.major + self.minor + self.near_miss


@dataclass
class IncidentBreakdown:
    """Incident breakdown with count and percentage"""
    count: int
    percentage: float


@dataclass
class SafetySummary:
    """Summary statistics"""
    total_manhours: float
    total_incidents: int
    incident_rate: float
    severity_score: int
    status: str  # 'safe' | 'moderate' | 'high_risk' | 'critical'


@dataclass
class PyramidItem:
    """Pyramid visualization item"""
    label: str
    value: int
    color: str


# ============================================================================
# SERVICE FUNCTIONS
# ============================================================================

def validate_input(data: Dict[str, Any]) -> HealthSafetyInput:
    """
    Validate and parse input data
    
    Args:
        data: Input dictionary with totalManhours and incidents
        
    Returns:
        HealthSafetyInput object
        
    Raises:
        ValueError: If validation fails
    """
    # Get total manhours
    total_manhours = data.get('totalManhours')
    if total_manhours is None:
        raise ValueError("totalManhours is required")
    
    if not isinstance(total_manhours, (int, float)) or total_manhours < 0:
        raise ValueError("totalManhours must be a non-negative number")
    
    # Get incidents
    incidents = data.get('incidents', {})
    if not isinstance(incidents, dict):
        raise ValueError("incidents must be a dictionary")
    
    # Extract incident values
    def get_incident(key: str, default: int = 0) -> int:
        value = incidents.get(key, default)
        if not isinstance(value, int) or value < 0:
            raise ValueError(f"incidents.{key} must be a non-negative integer")
        return value
    
    return HealthSafetyInput(
        total_manhours=float(total_manhours),
        fatalities=get_incident('fatalities', 0),
        significant=get_incident('significant', 0),
        major=get_incident('major', 0),
        minor=get_incident('minor', 0),
        near_miss=get_incident('nearMiss', 0)
    )


def calculate_incident_percentage(count: int, total: int) -> float:
    """
    Calculate percentage of incidents
    
    Args:
        count: Number of incidents in category
        total: Total number of incidents
        
    Returns:
        Percentage rounded to 2 decimal places
    """
    if total == 0:
        return 0.0
    return round((count / total) * 100, 2)


def calculate_incident_rate(total_incidents: int, total_manhours: float) -> float:
    """
    Calculate incident rate per 1,000,000 manhours
    
    Args:
        total_incidents: Total number of incidents
        total_manhours: Total manhours worked
        
    Returns:
        Incident rate per 1,000,000 manhours
    """
    if total_manhours == 0:
        return 0.0
    return round((total_incidents / total_manhours) * 1_000_000, 2)


def calculate_severity_score(input_data: HealthSafetyInput) -> int:
    """
    Calculate severity score using weighted formula
    
    Formula:
    severityScore = (fatalities * 5) + (significant * 4) + 
                   (major * 3) + (minor * 2) + (nearMiss * 1)
    
    Args:
        input_data: Health safety input data
        
    Returns:
        Severity score
    """
    return (
        input_data.fatalities * SEVERITY_WEIGHTS['fatalities'] +
        input_data.significant * SEVERITY_WEIGHTS['significant'] +
        input_data.major * SEVERITY_WEIGHTS['major'] +
        input_data.minor * SEVERITY_WEIGHTS['minor'] +
        input_data.near_miss * SEVERITY_WEIGHTS['near_miss']
    )


def determine_safety_status(input_data: HealthSafetyInput, incident_rate: float) -> str:
    """
    Determine safety status based on incidents and thresholds
    
    Logic:
    - IF fatalities > 0 → "critical"
    - ELSE IF significant > threshold → "high_risk"
    - ELSE IF incidentRate > threshold → "moderate"
    - ELSE → "safe"
    
    Args:
        input_data: Health safety input data
        incident_rate: Calculated incident rate
        
    Returns:
        Safety status: 'safe' | 'moderate' | 'high_risk' | 'critical'
    """
    # Check for fatalities (critical)
    if input_data.fatalities > 0:
        return 'critical'
    
    # Check for high significant incidents
    if input_data.significant > SafetyThresholds.SIGNIFICANT_THRESHOLD:
        return 'high_risk'
    
    # Check incident rate
    if incident_rate > SafetyThresholds.INCIDENT_RATE_THRESHOLD:
        return 'moderate'
    
    # Default to safe
    return 'safe'


def calculate_severity_index(severity_score: int) -> float:
    """
    Calculate normalized severity index (0-100)
    
    Args:
        severity_score: Raw severity score
        
    Returns:
        Normalized severity index (0-100)
    """
    if SafetyThresholds.MAX_SEVERITY_SCORE == 0:
        return 0.0
    
    index = (severity_score / SafetyThresholds.MAX_SEVERITY_SCORE) * 100
    return round(min(index, 100.0), 2)


def generate_pyramid_data(input_data: HealthSafetyInput) -> List[Dict[str, Any]]:
    """
    Generate pyramid visualization data
    
    Args:
        input_data: Health safety input data
        
    Returns:
        List of pyramid items ordered from most severe to least severe
    """
    pyramid_items = [
        {
            'label': SEVERITY_LABELS['fatalities'],
            'value': input_data.fatalities,
            'color': PYRAMID_COLORS['fatalities']
        },
        {
            'label': SEVERITY_LABELS['significant'],
            'value': input_data.significant,
            'color': PYRAMID_COLORS['significant']
        },
        {
            'label': SEVERITY_LABELS['major'],
            'value': input_data.major,
            'color': PYRAMID_COLORS['major']
        },
        {
            'label': SEVERITY_LABELS['minor'],
            'value': input_data.minor,
            'color': PYRAMID_COLORS['minor']
        },
        {
            'label': SEVERITY_LABELS['near_miss'],
            'value': input_data.near_miss,
            'color': PYRAMID_COLORS['near_miss']
        },
    ]
    
    return pyramid_items


def generate_insights(input_data: HealthSafetyInput, status: str) -> List[str]:
    """
    Generate human-readable insights based on the data
    
    Args:
        input_data: Health safety input data
        status: Current safety status
        
    Returns:
        List of insight strings
    """
    insights = []
    
    # Status-based insights
    if status == 'critical':
        insights.append("CRITICAL: Fatalities have been recorded. Immediate action required!")
    elif status == 'high_risk':
        insights.append("High risk level - significant incidents require attention")
    elif status == 'moderate':
        insights.append("Moderate incident rate - continue monitoring")
    else:
        insights.append("Safety status is good - maintain current practices")
    
    # Category-specific insights
    if input_data.fatalities > 0:
        insights.append(f"Warning: {input_data.fatalities} fatality(ies) recorded")
    
    if input_data.significant > 0:
        insights.append(f"{input_data.significant} significant incident(s) need investigation")
    
    if input_data.major > 0:
        insights.append(f"{input_data.major} major incident(s) require follow-up")
    
    if input_data.minor > 0:
        insights.append(f"{input_data.minor} minor incident(s) recorded")
    
    if input_data.near_miss > 0:
        insights.append(f"{input_data.near_miss} near miss(es) indicate potential future risks")
        if input_data.near_miss > SafetyThresholds.HIGH_NEAR_MISS_THRESHOLD:
            insights.append("High near-miss count suggests underlying safety issues")
    
    # Trend-like insights (based on proportions)
    if input_data.total_incidents > 0:
        # Check if near misses are high proportion
        near_miss_ratio = input_data.near_miss / input_data.total_incidents
        if near_miss_ratio > 0.5:
            insights.append("High proportion of near misses - investigate root causes")
        
        # Check if serious incidents dominate
        serious_count = input_data.fatalities + input_data.significant + input_data.major
        if serious_count > input_data.total_incidents * 0.5 and input_data.total_incidents > 3:
            insights.append("Majority of incidents are serious - review safety protocols")
    
    return insights


def generate_alerts(input_data: HealthSafetyInput) -> Dict[str, bool]:
    """
    Generate alert flags
    
    Args:
        input_data: Health safety input data
        
    Returns:
        Dictionary of alert flags
    """
    return {
        'hasFatality': input_data.fatalities > 0,
        'highNearMiss': input_data.near_miss > SafetyThresholds.HIGH_NEAR_MISS_THRESHOLD
    }


def calculate_health_safety_status(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main service function - calculates all health & safety metrics
    
    Args:
        data: Input dictionary with totalManhours and incidents
        
    Returns:
        Complete response with summary, breakdown, pyramid, and insights
    """
    # Step 1: Validate and parse input
    input_data = validate_input(data)
    
    # Step 2: Calculate total incidents
    total_incidents = input_data.total_incidents
    
    # Step 3: Calculate incident rate (per 1,000,000 manhours)
    incident_rate = calculate_incident_rate(total_incidents, input_data.total_manhours)
    
    # Step 4: Calculate severity score
    severity_score = calculate_severity_score(input_data)
    
    # Step 5: Determine safety status
    status = determine_safety_status(input_data, incident_rate)
    
    # Step 6: Generate breakdown with percentages
    breakdown = {
        'fatalities': IncidentBreakdown(
            count=input_data.fatalities,
            percentage=calculate_incident_percentage(input_data.fatalities, total_incidents)
        ),
        'significant': IncidentBreakdown(
            count=input_data.significant,
            percentage=calculate_incident_percentage(input_data.significant, total_incidents)
        ),
        'major': IncidentBreakdown(
            count=input_data.major,
            percentage=calculate_incident_percentage(input_data.major, total_incidents)
        ),
        'minor': IncidentBreakdown(
            count=input_data.minor,
            percentage=calculate_incident_percentage(input_data.minor, total_incidents)
        ),
        'nearMiss': IncidentBreakdown(
            count=input_data.near_miss,
            percentage=calculate_incident_percentage(input_data.near_miss, total_incidents)
        ),
    }
    
    # Step 7: Generate pyramid data
    pyramid = generate_pyramid_data(input_data)
    
    # Step 8: Generate insights
    insights = generate_insights(input_data, status)
    
    # Step 9: Generate alerts
    alerts = generate_alerts(input_data)
    
    # Step 10: Calculate severity index
    severity_index = calculate_severity_index(severity_score)
    
    # Build final response
    response = {
        'summary': {
            'totalManhours': input_data.total_manhours,
            'totalIncidents': total_incidents,
            'incidentRate': incident_rate,
            'severityScore': severity_score,
            'status': status
        },
        'breakdown': {
            'fatalities': {'count': breakdown['fatalities'].count, 'percentage': breakdown['fatalities'].percentage},
            'significant': {'count': breakdown['significant'].count, 'percentage': breakdown['significant'].percentage},
            'major': {'count': breakdown['major'].count, 'percentage': breakdown['major'].percentage},
            'minor': {'count': breakdown['minor'].count, 'percentage': breakdown['minor'].percentage},
            'nearMiss': {'count': breakdown['nearMiss'].count, 'percentage': breakdown['nearMiss'].percentage},
        },
        'pyramid': pyramid,
        'insights': insights,
        'alerts': alerts,
        'severityIndex': severity_index
    }
    
    return response
