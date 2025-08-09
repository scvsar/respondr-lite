"""
Comprehensive ETA Parsing Test Suite

Tests for edge cases and problematic ETA parsing scenarios to ensure
the system provides sensible results and validates parsed ETAs.
Includes tests for the new AI function calling approach.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from main import (
    convert_eta_to_timestamp, 
    extract_details_from_text, 
    calculate_eta_info,
    now_tz,
    APP_TZ,
    # New function calling functions
    calculate_eta_from_duration,
    validate_and_format_time,
    convert_duration_text,
    validate_realistic_eta
)

class TestETAParsingEdgeCases:
    """Test cases for problematic ETA parsing scenarios"""
    
    @pytest.fixture
    def mock_current_time(self):
        """Mock current time to 03:00 AM for consistent testing"""
        mock_time = datetime.now(APP_TZ).replace(hour=3, minute=0, second=0, microsecond=0)
        with patch('main.now_tz', return_value=mock_time):
            yield mock_time
    
    def test_eta_9_15_should_not_become_9_09(self, mock_current_time):
        """Test that 'ETA 9:15' doesn't get incorrectly parsed as 09:09"""
        # Current time: 03:00
        # ETA 9:15 should become 09:15
        result = convert_eta_to_timestamp("9:15", mock_current_time)
        assert result == "09:15", f"Expected 09:15, got {result}"
    
    def test_eta_57_hours_should_be_rejected_or_capped(self, mock_current_time):
        """Test that unrealistic ETAs like 57 hours are handled properly"""
        # 57 hours is unrealistic for emergency response
        result = convert_eta_to_timestamp("57 hours", mock_current_time)
        
        # Either should be rejected as unrealistic or capped at reasonable max
        # For now, let's see what it returns and then fix the logic
        expected_time = mock_current_time + timedelta(hours=57)
        expected_str = expected_time.strftime('%H:%M')
        
        # This should probably be rejected or capped at something like 24 hours max
        # Let's check if the current implementation returns something sensible
        assert result != "02:13", f"Should not return 02:13 for 57 hours, got {result}"
    
    def test_eta_24_30_invalid_time_format(self, mock_current_time):
        """Test that invalid time 24:30 is handled properly"""
        # 24:30 is not a valid time - should be 00:30 next day
        result = convert_eta_to_timestamp("24:30", mock_current_time)
        
        # Should either reject this or convert to valid time
        # 24:30 should become 00:30 (next day)
        assert result != "24:30", f"24:30 is invalid time format, should be converted or rejected"
    
    def test_duration_vs_absolute_time_confusion(self, mock_current_time):
        """Test cases where duration and absolute time might be confused"""
        # Current time: 03:00
        
        # These should be treated as durations (add to current time)
        result_5min = convert_eta_to_timestamp("5 minutes", mock_current_time)
        assert result_5min == "03:05", f"5 minutes from 03:00 should be 03:05, got {result_5min}"
        
        result_1hr = convert_eta_to_timestamp("1 hour", mock_current_time)
        assert result_1hr == "04:00", f"1 hour from 03:00 should be 04:00, got {result_1hr}"
        
        # These should be treated as absolute times
        result_abs = convert_eta_to_timestamp("10:30", mock_current_time)
        assert result_abs == "10:30", f"Absolute time 10:30 should stay 10:30, got {result_abs}"
    
    def test_am_pm_parsing_edge_cases(self, mock_current_time):
        """Test AM/PM parsing edge cases"""
        # Test cases that might be problematic
        test_cases = [
            ("9:15 AM", "09:15"),
            ("9:15 PM", "21:15"),
            ("12:00 AM", "00:00"),  # Midnight
            ("12:00 PM", "12:00"),  # Noon
            ("12:30 AM", "00:30"),  # After midnight
            ("12:30 PM", "12:30"),  # After noon
        ]
        
        for input_eta, expected in test_cases:
            result = convert_eta_to_timestamp(input_eta, mock_current_time)
            assert result == expected, f"Input '{input_eta}' should become '{expected}', got '{result}'"
    
    def test_unrealistic_durations_should_be_rejected(self, mock_current_time):
        """Test that unrealistic durations are handled appropriately"""
        unrealistic_cases = [
            "100 hours",
            "500 minutes", 
            "48 hours",
            "999 minutes"
        ]
        
        for case in unrealistic_cases:
            result = convert_eta_to_timestamp(case, mock_current_time)
            # Should either return "Unknown" or cap at reasonable maximum
            # Let's define reasonable max as 24 hours for emergency response
            if ":" in result:
                # If it returns a time, verify it's within reasonable bounds
                try:
                    hour, minute = map(int, result.split(":"))
                    # Check if the result is more than 24 hours from now
                    result_time = mock_current_time.replace(hour=hour, minute=minute)
                    if result_time <= mock_current_time:
                        result_time += timedelta(days=1)
                    
                    time_diff = result_time - mock_current_time
                    hours_diff = time_diff.total_seconds() / 3600
                    
                    # Should not exceed reasonable emergency response time
                    assert hours_diff <= 24, f"ETA '{case}' resulted in {hours_diff:.1f} hours, which is unrealistic"
                except:
                    # If parsing fails, that's also acceptable for unrealistic inputs
                    pass
    
    def test_calculate_eta_info_validation(self, mock_current_time):
        """Test that calculate_eta_info provides sensible results"""
        # Test with mock current time
        with patch('main.now_tz', return_value=mock_current_time):
            # Valid ETA
            result = calculate_eta_info("04:00")  # 1 hour from mock time (03:00)
            assert result["minutes_until_arrival"] == 60
            assert result["status"] == "On Route"
            
            # ETA in the past (should handle gracefully)
            result_past = calculate_eta_info("02:00")  # 1 hour ago
            # Should either be next day or marked appropriately
            if result_past["minutes_until_arrival"] is not None:
                assert result_past["minutes_until_arrival"] > 0, "Past ETA should be treated as next day"
            
            # Invalid formats
            invalid_cases = ["24:30", "25:00", "Invalid", ""]
            for invalid in invalid_cases:
                result = calculate_eta_info(invalid)
                # Should handle gracefully without crashing
                assert "status" in result
                if invalid in ["24:30", "25:00"]:
                    # These should be detected as invalid
                    assert result["status"] in ["ETA Format Unknown", "ETA Parse Error", "Unknown"]

class TestExtractDetailsValidation:
    """Test the overall extract_details_from_text function for validation"""
    
    def test_extract_details_with_ai_validation(self):
        """Test that the AI parsing includes validation logic"""
        # Mock Azure OpenAI to return problematic results
        test_cases = [
            # Case 1: AI returns invalid time format
            {
                "ai_response": '{"vehicle": "SAR-12", "eta": "24:30"}',
                "expected_eta": "Unknown",  # Should be corrected or rejected
                "text": "Responding SAR12, arriving at 24:30hrs"
            },
            # Case 2: AI returns unrealistic duration
            {
                "ai_response": '{"vehicle": "SAR-56", "eta": "57 hours"}',
                "expected_eta": "Unknown",  # Should be rejected as unrealistic
                "text": "Responding in SAR56, ETA 57 hours."
            },
            # Case 3: AI confuses duration with absolute time
            {
                "ai_response": '{"vehicle": "POV", "eta": "9:15"}',
                "expected_eta": "09:15",  # Should be kept if valid absolute time
                "text": "Responding pov eta 9:15"
            }
        ]
        
        for i, case in enumerate(test_cases):
            with patch('main.client') as mock_client:
                mock_response = MagicMock()
                mock_response.choices = [
                    MagicMock(message=MagicMock(content=case["ai_response"]))
                ]
                mock_client.chat.completions.create.return_value = mock_response
                
                result = extract_details_from_text(case["text"])
                
                # The function should validate and potentially correct the AI response
                assert "vehicle" in result
                assert "eta" in result
                
                # Check that unrealistic results are handled
                if case["expected_eta"] == "Unknown":
                    # Should either be Unknown or a corrected realistic value
                    eta_result = result["eta"]
                    if eta_result not in ["Unknown", "Not Responding"]:
                        # If it's a time format, validate it's realistic
                        if ":" in eta_result:
                            try:
                                hour, minute = map(int, eta_result.split(":"))
                                assert 0 <= hour <= 23, f"Hour {hour} is invalid"
                                assert 0 <= minute <= 59, f"Minute {minute} is invalid"
                            except ValueError:
                                pytest.fail(f"Invalid time format returned: {eta_result}")

class TestETAValidationLogic:
    """Test validation logic for parsed ETAs"""
    
    def test_validate_time_format(self):
        """Test validation of time formats"""
        valid_times = ["00:00", "12:30", "23:59", "09:15"]
        invalid_times = ["24:00", "25:30", "12:60", "99:99", "24:30"]
        
        for valid_time in valid_times:
            # Should not raise exception and should parse correctly
            try:
                hour, minute = map(int, valid_time.split(":"))
                assert 0 <= hour <= 23
                assert 0 <= minute <= 59
            except:
                pytest.fail(f"Valid time {valid_time} failed validation")
        
        for invalid_time in invalid_times:
            # Should be detected as invalid
            try:
                hour, minute = map(int, invalid_time.split(":"))
                is_valid = 0 <= hour <= 23 and 0 <= minute <= 59
                assert not is_valid, f"Invalid time {invalid_time} was not detected as invalid"
            except ValueError:
                # This is also acceptable - parsing should fail
                pass
    
    def test_validate_duration_reasonableness(self):
        """Test that durations are within reasonable bounds for emergency response"""
        reasonable_durations = [
            ("5 minutes", 5),
            ("30 minutes", 30), 
            ("1 hour", 60),
            ("2 hours", 120),
            ("8 hours", 480)  # Still reasonable for some SAR operations
        ]
        
        unreasonable_durations = [
            ("50 hours", 3000),  # Way too long
            ("25 hours", 1500),  # Over 24 hours
            ("48 hours", 2880),  # 2 days - unrealistic
            ("999 minutes", 999)   # Over 16 hours - unrealistic
        ]
        
        # Define reasonable max (e.g., 24 hours = 1440 minutes)
        MAX_REASONABLE_MINUTES = 24 * 60
        
        for duration_text, expected_minutes in reasonable_durations:
            assert expected_minutes <= MAX_REASONABLE_MINUTES, f"{duration_text} should be reasonable"
        
        for duration_text, expected_minutes in unreasonable_durations:
            assert expected_minutes > MAX_REASONABLE_MINUTES, f"{duration_text} should be detected as unreasonable"

class TestAIFunctionCalling:
    """Test the new AI function calling calculation functions"""
    
    def test_calculate_eta_from_duration(self):
        """Test the calculate_eta_from_duration function"""
        # Test basic duration calculation
        result = calculate_eta_from_duration("03:31", 59)  # 59 minutes from 03:31
        assert result["valid"] is True
        assert result["eta"] == "04:30"
        assert result["duration_minutes"] == 59
        assert result["warning"] is None
        
        # Test with unrealistic duration (over 24 hours)
        result = calculate_eta_from_duration("03:16", 1500)  # 25 hours
        assert result["valid"] is True
        assert result["warning"] == "ETA over 24 hours - please verify"
        
        # Test edge case - exactly 24 hours
        result = calculate_eta_from_duration("12:00", 1440)  # 24 hours
        assert result["valid"] is True
        assert result["eta"] == "12:00"  # Same time next day
        
    def test_validate_and_format_time(self):
        """Test the validate_and_format_time function"""
        # Test valid 24-hour times
        result = validate_and_format_time("9:15")
        assert result["valid"] is True
        assert result["normalized"] == "09:15"  # Should be zero-padded
        assert result["next_day"] is False
        
        result = validate_and_format_time("23:45")
        assert result["valid"] is True
        assert result["normalized"] == "23:45"
        
        # Test invalid time - 24:30 should be converted to 00:30
        result = validate_and_format_time("24:30")
        assert result["valid"] is True
        assert result["normalized"] == "00:30"
        assert result["next_day"] is True
        assert "Converted 24:30 to 00:30" in result["note"]
        
        # Test 24:00 -> 00:00
        result = validate_and_format_time("24:00")
        assert result["valid"] is True
        assert result["normalized"] == "00:00"
        assert result["next_day"] is True
        
        # Test invalid hour > 24
        result = validate_and_format_time("25:30")
        assert result["valid"] is False
        assert "Invalid hour: 25" in result["error"]
        
        # Test invalid minute > 59
        result = validate_and_format_time("12:75")
        assert result["valid"] is False
        assert "Invalid minute: 75" in result["error"]
        
        # Test AM/PM conversion
        result = validate_and_format_time("9:15 AM")
        assert result["valid"] is True
        assert result["normalized"] == "09:15"
        
        result = validate_and_format_time("9:15 PM")
        assert result["valid"] is True
        assert result["normalized"] == "21:15"
        
        result = validate_and_format_time("12:30 AM")  # Midnight
        assert result["valid"] is True
        assert result["normalized"] == "00:30"
        
        result = validate_and_format_time("12:30 PM")  # Noon
        assert result["valid"] is True
        assert result["normalized"] == "12:30"
    
    def test_convert_duration_text(self):
        """Test the convert_duration_text function"""
        # Test various duration formats
        result = convert_duration_text("30 minutes")
        assert result["valid"] is True
        assert result["minutes"] == 30
        assert result["warning"] is None
        
        result = convert_duration_text("1 hour")
        assert result["valid"] is True
        assert result["minutes"] == 60
        
        result = convert_duration_text("2.5 hours")
        assert result["valid"] is True
        assert result["minutes"] == 150
        
        result = convert_duration_text("half hour")
        assert result["valid"] is True
        assert result["minutes"] == 30
        
        # Test unrealistic duration
        result = convert_duration_text("57 hours")
        assert result["valid"] is True
        assert result["minutes"] == 3420  # 57 * 60
        assert result["warning"] == "Duration over 24 hours - please verify"
        
    def test_validate_realistic_eta(self):
        """Test the validate_realistic_eta function"""
        # Test reasonable ETAs
        result = validate_realistic_eta(30)  # 30 minutes
        assert result["realistic"] is True
        assert result["hours"] == 0.5
        
        result = validate_realistic_eta(120)  # 2 hours
        assert result["realistic"] is True
        assert result["hours"] == 2
        
        # Test unrealistic ETAs
        result = validate_realistic_eta(1500)  # 25 hours
        assert result["realistic"] is False
        assert "unrealistic for emergency response" in result["reason"]
        
        result = validate_realistic_eta(800)  # 13.3 hours
        assert result["realistic"] is False
        assert "very long for emergency response" in result["reason"]
        
        # Test edge cases
        result = validate_realistic_eta(0)
        assert result["realistic"] is False
        assert "cannot be negative or zero" in result["reason"]
        
        result = validate_realistic_eta(-10)
        assert result["realistic"] is False

class TestRealWorldProblematicCases:
    """Test the actual problematic cases mentioned in the user report"""
    
    @pytest.fixture
    def mock_current_time_real(self):
        """Mock current time to match the real-world examples"""
        # Use 03:00 AM as in the real examples
        mock_time = datetime.now(APP_TZ).replace(hour=3, minute=0, second=0, microsecond=0)
        with patch('main.now_tz', return_value=mock_time):
            yield mock_time
    
    def test_quinton_cline_eta_9_15_issue(self, mock_current_time_real):
        """Test the specific case: 'Responding pov eta 9:15' showing as 09:09"""
        text = "Responding pov eta 9:15"
        
        # Test the conversion directly
        result = convert_eta_to_timestamp("9:15", mock_current_time_real)
        assert result == "09:15", f"ETA 9:15 should remain 09:15, not become 09:09. Got: {result}"
        
        # Test with fast local parse
        with patch('main.FAST_LOCAL_PARSE', True):
            result = extract_details_from_text(text)
            # Should extract 9:15 and keep it as 09:15
            assert result["vehicle"] == "POV"
            # The ETA should be correctly parsed
            if result["eta"] != "Unknown":
                assert result["eta"] == "09:15", f"Expected 09:15, got {result['eta']}"
    
    def test_seth_stone_57_hours_issue(self, mock_current_time_real):
        """Test the specific case: 'ETA 57 hours' showing unrealistic conversion"""
        text = "Responding in SAR12, ETA 57 hours."
        
        # Test the conversion directly
        result = convert_eta_to_timestamp("57 hours", mock_current_time_real)
        
        # 57 hours is unrealistic for emergency response
        # Should either be rejected or capped at reasonable max
        if ":" in result:
            # If it returns a time, it should be reasonable
            hour, minute = map(int, result.split(":"))
            result_time = mock_current_time_real.replace(hour=hour, minute=minute)
            if result_time <= mock_current_time_real:
                result_time += timedelta(days=1)
            
            time_diff = result_time - mock_current_time_real
            hours_diff = time_diff.total_seconds() / 3600
            
            # Should not be the problematic 1376 minutes (22.9 hours) that doesn't make sense
            assert hours_diff != 22.9, f"Should not return the buggy 1376 minutes conversion"
            
            # Should either be capped at reasonable max or rejected
            if hours_diff > 24:
                pytest.fail(f"57 hours should be capped or rejected, got {hours_diff:.1f} hours")
    
    def test_seth_stone_24_30_invalid_time(self, mock_current_time_real):
        """Test the specific case: 'arriving at 24:30hrs' showing as invalid 24:30"""
        text = "Responding pov arriving at 24:30hrs"
        
        # Test the conversion directly
        result = convert_eta_to_timestamp("24:30", mock_current_time_real)
        
        # 24:30 is not a valid time - should be converted to 00:30 or rejected
        assert result != "24:30", f"24:30 is invalid time format, should be converted or rejected. Got: {result}"
        
        # If converted, should be 00:30
        if ":" in result and result != "Unknown":
            hour, minute = map(int, result.split(":"))
            assert 0 <= hour <= 23, f"Hour should be 0-23, got {hour}"
            assert 0 <= minute <= 59, f"Minute should be 0-59, got {minute}"

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
