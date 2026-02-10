"""
Tests for timezone utility functions
"""
import pytest
from datetime import datetime, timezone
import pytz
from backend.utils.timezone_utils import (
    get_display_timezone,
    convert_utc_to_display,
    convert_display_to_utc,
    utc_now,
    parse_datetime_string,
    format_datetime_for_display,
    format_datetime_for_api
)

class TestTimezoneUtils:
    
    def test_get_display_timezone(self):
        """Test that get_display_timezone returns the correct default timezone"""
        tz = get_display_timezone()
        assert tz == "Asia/Singapore"
    
    def test_convert_utc_to_display(self):
        """Test UTC to display timezone conversion"""
        # Create UTC datetime
        utc_dt = datetime(2023, 5, 15, 10, 30, 0, tzinfo=timezone.utc)
        
        # Convert to display timezone (Singapore)
        display_dt = convert_utc_to_display(utc_dt)
        
        # Should be 6:30 PM in Singapore (UTC+8)
        assert display_dt.hour == 18
        assert display_dt.minute == 30
        assert display_dt.tzinfo.zone == "Asia/Singapore"
    
    def test_convert_display_to_utc(self):
        """Test display timezone to UTC conversion"""
        # Create datetime in Singapore timezone
        sg_tz = pytz.timezone("Asia/Singapore")
        sg_dt = sg_tz.localize(datetime(2023, 5, 15, 18, 30, 0))
        
        # Convert to UTC
        utc_dt = convert_display_to_utc(sg_dt)
        
        # Should be 10:30 AM UTC
        assert utc_dt.hour == 10
        assert utc_dt.minute == 30
        assert utc_dt.tzinfo == timezone.utc
    
    def test_utc_now(self):
        """Test utc_now returns timezone-aware UTC datetime"""
        now = utc_now()
        assert now.tzinfo == timezone.utc
        assert isinstance(now, datetime)
    
    def test_parse_datetime_string_iso(self):
        """Test parsing ISO format datetime string"""
        iso_string = "2023-05-15T10:30:00Z"
        dt = parse_datetime_string(iso_string)
        assert dt is not None
        assert dt.tzinfo == timezone.utc
        assert dt.year == 2023
        assert dt.month == 5
        assert dt.day == 15
        assert dt.hour == 10
        assert dt.minute == 30
    
    def test_parse_datetime_string_naive(self):
        """Test parsing naive datetime string (assumed to be in display timezone)"""
        naive_string = "2023-05-15 18:30:00"
        dt = parse_datetime_string(naive_string)
        assert dt is not None
        assert dt.tzinfo == timezone.utc
        # Should convert 6:30 PM Singapore time to 10:30 AM UTC
        assert dt.hour == 10
        assert dt.minute == 30
    
    def test_parse_datetime_string_invalid(self):
        """Test parsing invalid datetime string raises ValueError"""
        with pytest.raises(ValueError):
            parse_datetime_string("invalid-date-format")
    
    def test_format_datetime_for_display(self):
        """Test formatting UTC datetime for display"""
        utc_dt = datetime(2023, 5, 15, 10, 30, 0, tzinfo=timezone.utc)
        formatted = format_datetime_for_display(utc_dt, "%d/%m/%Y %H:%M")
        # Should be 18:30 in Singapore time
        assert formatted == "15/05/2023 18:30"
    
    def test_format_datetime_for_api(self):
        """Test formatting datetime for API response"""
        utc_dt = datetime(2023, 5, 15, 10, 30, 0, tzinfo=timezone.utc)
        formatted = format_datetime_for_api(utc_dt)
        assert formatted == "2023-05-15T10:30:00Z"
    
    def test_convert_utc_to_display_string_input(self):
        """Test UTC to display conversion with string input"""
        utc_string = "2023-05-15T10:30:00Z"
        display_dt = convert_utc_to_display(utc_string)
        assert display_dt.tzinfo.zone == "Asia/Singapore"
        assert display_dt.hour == 18  # 10:30 UTC = 18:30 SGT
    
    def test_convert_display_to_utc_string_input(self):
        """Test display to UTC conversion with string input"""
        display_string = "2023-05-15T18:30:00+08:00"  # Singapore time
        utc_dt = convert_display_to_utc(display_string)
        assert utc_dt.tzinfo == timezone.utc
        assert utc_dt.hour == 10  # 18:30 SGT = 10:30 UTC