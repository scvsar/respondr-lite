"""
Test file to demonstrate enhanced AI function calling for ETA parsing.
This shows how we could give the AI tools to calculate correct values itself.
"""
from datetime import datetime, timedelta
import pytz
from typing import Dict, Any

# Mock functions that the AI could call
def calculate_eta_from_duration(current_time: str, duration_minutes: int) -> str:
    """Calculate ETA by adding duration to current time."""
    try:
        # Parse current time (format: "HH:MM")
        hour, minute = map(int, current_time.split(':'))
        
        # Create datetime for calculation (use today's date)
        base_time = datetime.now().replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        
        # Add duration
        eta_time = base_time + timedelta(minutes=duration_minutes)
        
        # Return in HH:MM format
        return eta_time.strftime("%H:%M")
    except Exception as e:
        raise ValueError(f"Error calculating ETA: {e}")

def validate_time_format(time_string: str) -> Dict[str, Any]:
    """Validate and normalize time format."""
    try:
        # Handle 24-hour format
        if ':' in time_string:
            parts = time_string.replace(':', '').replace(' ', '')
            if len(parts) == 4 and parts.isdigit():
                hour = int(parts[:2])
                minute = int(parts[2:])
                
                # Validate ranges
                if hour > 23:
                    # Handle 24:xx as 00:xx next day
                    if hour == 24 and minute < 60:
                        return {"valid": True, "normalized": f"00:{minute:02d}", "next_day": True}
                    else:
                        return {"valid": False, "error": f"Invalid hour: {hour}"}
                
                if minute > 59:
                    return {"valid": False, "error": f"Invalid minute: {minute}"}
                
                return {"valid": True, "normalized": f"{hour:02d}:{minute:02d}", "next_day": False}
        
        return {"valid": False, "error": "Invalid time format"}
    except Exception as e:
        return {"valid": False, "error": str(e)}

def convert_duration_to_minutes(duration_text: str) -> int:
    """Convert various duration formats to minutes."""
    duration_lower = duration_text.lower()
    
    # Hours
    if 'hour' in duration_lower:
        if 'half' in duration_lower:
            return 30
        # Extract number of hours
        import re
        match = re.search(r'(\d+(?:\.\d+)?)', duration_lower)
        if match:
            hours = float(match.group(1))
            return int(hours * 60)
    
    # Minutes
    if 'min' in duration_lower:
        import re
        match = re.search(r'(\d+)', duration_lower)
        if match:
            return int(match.group(1))
    
    # Direct number extraction for common cases
    import re
    match = re.search(r'(\d+)', duration_text)
    if match:
        number = int(match.group(1))
        # Assume minutes if just a number
        if 'hour' not in duration_lower:
            return number
        else:
            return number * 60
    
    raise ValueError(f"Cannot parse duration: {duration_text}")

# Function definitions that would be passed to Azure OpenAI
FUNCTION_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "calculate_eta_from_duration",
            "description": "Calculate ETA by adding a duration in minutes to the current time",
            "parameters": {
                "type": "object",
                "properties": {
                    "current_time": {
                        "type": "string",
                        "description": "Current time in HH:MM format"
                    },
                    "duration_minutes": {
                        "type": "integer",
                        "description": "Duration to add in minutes"
                    }
                },
                "required": ["current_time", "duration_minutes"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "validate_time_format",
            "description": "Validate and normalize a time string to proper 24-hour format",
            "parameters": {
                "type": "object",
                "properties": {
                    "time_string": {
                        "type": "string",
                        "description": "Time string to validate (e.g., '24:30', '09:15')"
                    }
                },
                "required": ["time_string"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "convert_duration_to_minutes",
            "description": "Convert various duration text formats to minutes",
            "parameters": {
                "type": "object",
                "properties": {
                    "duration_text": {
                        "type": "string",
                        "description": "Duration text (e.g., '57 hours', '30 minutes', 'half hour')"
                    }
                },
                "required": ["duration_text"]
            }
        }
    }
]

# Enhanced prompt that instructs AI to use tools
ENHANCED_PROMPT_TEMPLATE = """
You are an expert at extracting responder information from SAR (Search and Rescue) messages.
You have access to calculation tools to ensure accuracy.

CURRENT TIME: {current_time}

INSTRUCTIONS:
1. Extract vehicle and ETA from the message
2. For ETAs, use the provided tools to calculate accurate times
3. Always validate time formats using the validation tool
4. For durations (e.g., "30 minutes", "1 hour"), use calculate_eta_from_duration
5. For specific times (e.g., "9:15", "24:30"), use validate_time_format first

VEHICLE RULES:
- SAR vehicles: return exact identifier (e.g., "SAR-12", "SAR-56")
- Personal vehicles: return "POV"
- Unknown/unclear: return "Unknown"

Message: "{message}"

Use the tools as needed, then return JSON: {{"vehicle": "value", "eta": "HH:MM|Unknown|Not Responding"}}
"""

class TestAIFunctionCalling:
    """Test the enhanced AI function calling approach."""
    
    def test_calculate_eta_from_duration(self):
        """Test the duration calculation tool."""
        result = calculate_eta_from_duration("03:31", 59)  # 59 minutes from 03:31
        assert result == "04:30"
        
        result = calculate_eta_from_duration("01:01", 40)  # 40 minutes from 01:01
        assert result == "01:41"
    
    def test_validate_time_format(self):
        """Test the time validation tool."""
        # Valid times
        result = validate_time_format("09:15")
        assert result["valid"] is True
        assert result["normalized"] == "09:15"
        
        # Invalid time - 24:30 should be 00:30 next day
        result = validate_time_format("24:30")
        assert result["valid"] is True
        assert result["normalized"] == "00:30"
        assert result["next_day"] is True
        
        # Invalid hour
        result = validate_time_format("25:30")
        assert result["valid"] is False
        assert "Invalid hour" in result["error"]
    
    def test_convert_duration_to_minutes(self):
        """Test duration parsing tool."""
        assert convert_duration_to_minutes("57 hours") == 3420  # 57 * 60
        assert convert_duration_to_minutes("30 minutes") == 30
        assert convert_duration_to_minutes("half hour") == 30
        assert convert_duration_to_minutes("1 hour") == 60
    
    def test_problematic_cases_with_tools(self):
        """Test how the tools would handle the problematic cases from the user's examples."""
        
        # Case 1: "ETA 9:15" - should validate and format properly
        validation = validate_time_format("9:15")
        assert validation["valid"] is True
        assert validation["normalized"] == "09:15"  # Properly zero-padded
        
        # Case 2: "ETA 57 hours" - should calculate correct minutes and ETA
        minutes = convert_duration_to_minutes("57 hours")
        assert minutes == 3420  # 57 * 60 = 3420 minutes
        
        eta = calculate_eta_from_duration("03:16", minutes)
        # 03:16 + 3420 minutes = 03:16 + 57 hours = 03:16 next day + 1 day + 9 hours = 12:16 day after tomorrow
        # But for practical SAR purposes, this should probably be flagged as unrealistic
        
        # Case 3: "arriving at 24:30hrs" - should normalize to 00:30
        validation = validate_time_format("24:30")
        assert validation["valid"] is True
        assert validation["normalized"] == "00:30"
        assert validation["next_day"] is True

def simulate_ai_with_function_calling(message: str, current_time: str) -> Dict[str, str]:
    """
    Simulate how the AI would work with function calling.
    In reality, this would be handled by Azure OpenAI's function calling feature.
    """
    
    # Example responses for the problematic cases
    test_cases = {
        "Responding pov eta 9:15": {
            "steps": [
                ("validate_time_format", {"time_string": "9:15"}),
            ],
            "result": {"vehicle": "POV", "eta": "09:15"}
        },
        "Responding in SAR12, ETA 57 hours": {
            "steps": [
                ("convert_duration_to_minutes", {"duration_text": "57 hours"}),
                ("calculate_eta_from_duration", {"current_time": current_time, "duration_minutes": 3420}),
            ],
            "result": {"vehicle": "SAR-12", "eta": "12:16", "warning": "ETA over 24 hours - please verify"}
        },
        "Responding pov arriving at 24:30hrs": {
            "steps": [
                ("validate_time_format", {"time_string": "24:30"}),
            ],
            "result": {"vehicle": "POV", "eta": "00:30", "note": "Converted 24:30 to 00:30 (next day)"}
        }
    }
    
    # Simulate the function calling process
    if message in test_cases:
        case = test_cases[message]
        
        # Execute the function calls
        for func_name, params in case["steps"]:
            if func_name == "validate_time_format":
                result = validate_time_format(params["time_string"])
                print(f"AI called {func_name}: {result}")
            elif func_name == "convert_duration_to_minutes":
                result = convert_duration_to_minutes(params["duration_text"])
                print(f"AI called {func_name}: {result} minutes")
            elif func_name == "calculate_eta_from_duration":
                result = calculate_eta_from_duration(params["current_time"], params["duration_minutes"])
                print(f"AI called {func_name}: {result}")
        
        return case["result"]
    
    return {"vehicle": "Unknown", "eta": "Unknown"}

class TestSimulatedFunctionCalling:
    """Test the simulated function calling approach."""
    
    def test_eta_9_15_case(self):
        """Test the 'ETA 9:15' case with function calling."""
        result = simulate_ai_with_function_calling("Responding pov eta 9:15", "03:19")
        assert result["vehicle"] == "POV"
        assert result["eta"] == "09:15"  # Properly formatted
    
    def test_eta_57_hours_case(self):
        """Test the 'ETA 57 hours' case with function calling."""
        result = simulate_ai_with_function_calling("Responding in SAR12, ETA 57 hours", "03:16")
        assert result["vehicle"] == "SAR-12"
        # The AI should flag this as unrealistic
        assert "warning" in result
    
    def test_arriving_24_30_case(self):
        """Test the 'arriving at 24:30hrs' case with function calling."""
        result = simulate_ai_with_function_calling("Responding pov arriving at 24:30hrs", "03:19")
        assert result["vehicle"] == "POV"
        assert result["eta"] == "00:30"  # Properly normalized
        assert "note" in result  # Should note the conversion

if __name__ == "__main__":
    # Run some examples
    print("Testing function calling approach...")
    
    print("\n1. ETA 9:15 case:")
    result1 = simulate_ai_with_function_calling("Responding pov eta 9:15", "03:19")
    print(f"Result: {result1}")
    
    print("\n2. ETA 57 hours case:")
    result2 = simulate_ai_with_function_calling("Responding in SAR12, ETA 57 hours", "03:16")
    print(f"Result: {result2}")
    
    print("\n3. Arriving at 24:30hrs case:")
    result3 = simulate_ai_with_function_calling("Responding pov arriving at 24:30hrs", "03:19")
    print(f"Result: {result3}")
