"""
Timezone utility functions for FleetWise application.
Handles conversion between UTC and display timezone (configurable, default Asia/Singapore).
"""

from datetime import datetime, timezone
import pytz
from typing import Optional, Union


def get_display_timezone() -> str:
    """
    Get the configured display timezone from system settings.
    For now, defaults to Asia/Singapore, but can be extended to read from settings.
    """
    # In production, this would read from system settings
    # For now, defaulting to Asia/Singapore as per requirements
    return "Asia/Singapore"


def convert_utc_to_display(utc_dt: Union[datetime, str]) -> datetime:
    """
    Convert a UTC datetime to the configured display timezone.
    
    Args:
        utc_dt: UTC datetime object or ISO string
        
    Returns:
        Datetime object in the display timezone
    """
    if isinstance(utc_dt, str):
        # Parse ISO format string to datetime object
        # Use safe approach: strip Z and make timezone aware
        if utc_dt.endswith('Z'):
            utc_dt = utc_dt[:-1]
        parsed_dt = datetime.fromisoformat(utc_dt)
        # Ensure timezone aware in UTC
        if parsed_dt.tzinfo is None:
            parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
        utc_dt = parsed_dt
    elif utc_dt.tzinfo != timezone.utc:
        # Convert to UTC if it's in another timezone
        utc_dt = utc_dt.astimezone(timezone.utc)
    
    # Convert to display timezone
    display_tz = pytz.timezone(get_display_timezone())
    display_dt = utc_dt.astimezone(display_tz)
    
    return display_dt


def convert_display_to_utc(display_dt: Union[datetime, str]) -> datetime:
    """
    Convert a datetime from the configured display timezone to UTC.
    
    Args:
        display_dt: Display timezone datetime object or ISO string
        
    Returns:
        Datetime object in UTC
    """
    if isinstance(display_dt, str):
        # Parse the string - assume it's in display timezone format
        # For now, we'll parse it as naive datetime and assign display timezone
        if display_dt.endswith('Z'):
            display_dt = display_dt[:-1]  # Remove 'Z' suffix
        parsed_dt = datetime.fromisoformat(display_dt.replace('Z', '+00:00'))
        
        # If it has timezone info, convert to naive and treat as display timezone
        if parsed_dt.tzinfo is not None:
            display_tz = pytz.timezone(get_display_timezone())
            display_dt = parsed_dt.astimezone(display_tz)
        else:
            # If no timezone info, assume it's in display timezone
            display_tz = pytz.timezone(get_display_timezone())
            display_dt = display_tz.localize(parsed_dt, is_dst=None)
    else:
        # If it's already a datetime object
        if display_dt.tzinfo is None:
            # Assume it's in display timezone
            display_tz = pytz.timezone(get_display_timezone())
            display_dt = display_tz.localize(display_dt, is_dst=None)
        elif display_dt.tzinfo is not None:
            # Safely compare timezone zones; stdlib timezones don't have a 'zone' attribute
            display_tz = pytz.timezone(get_display_timezone())
            if getattr(display_dt.tzinfo, "zone", None) != display_tz.zone:
                # Convert to display timezone if it's in another timezone
                display_dt = display_dt.astimezone(display_tz)
    
    # Convert to UTC
    utc_dt = display_dt.astimezone(timezone.utc)
    
    return utc_dt


def utc_now() -> datetime:
    """
    Get current time in UTC.
    
    Returns:
        Current datetime in UTC
    """
    return datetime.now(timezone.utc)


def parse_datetime_string(dt_string: str, tz_aware: bool = True) -> Optional[datetime]:
    """
    Parse a datetime string and return a timezone-aware datetime in UTC.
    
    Args:
        dt_string: String representation of datetime
        tz_aware: Whether to return timezone-aware datetime
        
    Returns:
        Parsed datetime object (timezone-aware in UTC by default)
    """
    if not dt_string:
        return None
    
    try:
        # Handle various common datetime formats
        dt = datetime.fromisoformat(dt_string.replace('Z', '+00:00'))
        
        # If it's naive, assume it's in the display timezone and convert to UTC
        if dt.tzinfo is None:
            display_tz = pytz.timezone(get_display_timezone())
            dt = display_tz.localize(dt)
            dt = dt.astimezone(timezone.utc)
        else:
            # If it has timezone info, convert to UTC
            dt = dt.astimezone(timezone.utc)
            
        return dt
    except ValueError:
        # If ISO format fails, try other common formats
        for fmt in [
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%d %H:%M:%S.%f',
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%dT%H:%M:%SZ',
            '%Y-%m-%dT%H:%M:%S.%fZ',
            '%Y-%m-%dT%H:%M:%S%z',
            '%d/%m/%Y %H:%M',
            '%d-%m-%Y %H:%M',
            '%Y/%m/%d %H:%M',
            '%Y-%m-%d',
            '%d/%m/%Y',
            '%d-%m-%Y'
        ]:
            try:
                dt = datetime.strptime(dt_string, fmt)
                
                # If it's just a date, set time to 00:00
                if fmt in ['%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y']:
                    dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
                
                # If it's naive, assume it's in the display timezone and convert to UTC
                display_tz = pytz.timezone(get_display_timezone())
                dt = display_tz.localize(dt, is_dst=None)
                dt = dt.astimezone(timezone.utc)
                
                return dt
            except ValueError:
                continue
                
        raise ValueError(f"Unable to parse datetime string: {dt_string}")


def format_datetime_for_display(utc_dt: datetime, fmt: str = "%d/%m/%Y %H:%M") -> str:
    """
    Format a UTC datetime for display in the configured timezone.
    
    Args:
        utc_dt: UTC datetime object
        fmt: Output format string
        
    Returns:
        Formatted datetime string in display timezone
    """
    if utc_dt is None:
        return ""
    
    # Ensure the datetime is in UTC
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    elif utc_dt.tzinfo != timezone.utc:
        utc_dt = utc_dt.astimezone(timezone.utc)
    
    # Convert to display timezone
    display_dt = convert_utc_to_display(utc_dt)
    
    return display_dt.strftime(fmt)


def format_datetime_for_api(utc_dt: datetime) -> str:
    """
    Format a datetime for API responses in ISO format.
    
    Args:
        utc_dt: Datetime object (will be converted to UTC if needed)
        
    Returns:
        ISO formatted datetime string in UTC
    """
    if utc_dt is None:
        return ""
    
    # Ensure the datetime is in UTC
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    elif utc_dt.tzinfo != timezone.utc:
        utc_dt = utc_dt.astimezone(timezone.utc)
    
    return utc_dt.isoformat().replace('+00:00', 'Z')