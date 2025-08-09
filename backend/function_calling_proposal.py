"""
Proposed implementation for Azure OpenAI Function Calling in respondr.
This shows how to integrate function calling to fix the ETA parsing issues.
"""

from typing import Dict, Any, List
import json
from datetime import datetime, timedelta

# Function definitions for Azure OpenAI
FUNCTION_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "calculate_eta_from_duration",
            "description": "Calculate accurate ETA by adding duration in minutes to current time",
            "parameters": {
                "type": "object",
                "properties": {
                    "current_time": {
                        "type": "string",
                        "description": "Current time in HH:MM format (24-hour)"
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
            "name": "validate_and_format_time",
            "description": "Validate time and convert to proper 24-hour format",
            "parameters": {
                "type": "object",
                "properties": {
                    "time_string": {
                        "type": "string",
                        "description": "Time to validate (e.g., '9:15', '24:30', '23:45')"
                    }
                },
                "required": ["time_string"]
            }
        }
    },
    {
        "type": "function", 
        "function": {
            "name": "convert_duration_text",
            "description": "Convert duration text to minutes with validation",
            "parameters": {
                "type": "object",
                "properties": {
                    "duration_text": {
                        "type": "string",
                        "description": "Duration text like '30 minutes', '2 hours', 'half hour'"
                    }
                },
                "required": ["duration_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "validate_realistic_eta",
            "description": "Check if ETA is realistic for SAR operations",
            "parameters": {
                "type": "object", 
                "properties": {
                    "eta_minutes": {
                        "type": "integer",
                        "description": "ETA duration in minutes"
                    }
                },
                "required": ["eta_minutes"]
            }
        }
    }
]

# Enhanced prompt for function calling
FUNCTION_CALLING_PROMPT = '''
You are an expert SAR (Search and Rescue) responder message parser with access to calculation tools.

CURRENT TIME: {current_time}

Use the provided functions to ensure accurate ETA calculations:

1. For duration-based ETAs (e.g., "30 minutes", "1 hour"):
   - Use convert_duration_text() to get minutes
   - Use validate_realistic_eta() to check if reasonable  
   - Use calculate_eta_from_duration() to get exact time

2. For specific times (e.g., "9:15", "24:30"):
   - Use validate_and_format_time() to normalize format

3. Always validate that results make sense for SAR operations

VEHICLE EXTRACTION:
- SAR vehicles: Extract exact identifier (SAR-12, SAR-56, etc.)  
- Personal vehicles: Return "POV"
- Unknown/unclear: Return "Unknown"

MESSAGE: "{message}"

Parse the message and return: {{"vehicle": "value", "eta": "HH:MM|Unknown|Not Responding"}}
'''

def create_enhanced_extract_function():
    """
    Returns the enhanced extract_details_from_text function that uses function calling.
    This would replace the current function in main.py.
    """
    code = '''
def extract_details_from_text_with_functions(text: str) -> Dict[str, str]:
    """Extract vehicle and ETA using Azure OpenAI with function calling."""
    
    if FAST_LOCAL_PARSE or client is None:
        # Fallback to existing logic
        return extract_details_from_text_original(text)
    
    try:
        current_time = now_tz()
        current_time_str = current_time.strftime("%H:%M")
        
        # Use function calling
        response = client.chat.completions.create(
            model=azure_openai_deployment,
            messages=[{
                "role": "user", 
                "content": FUNCTION_CALLING_PROMPT.format(
                    current_time=current_time_str,
                    message=text
                )
            }],
            functions=FUNCTION_DEFINITIONS,
            function_call="auto",  # Let AI decide when to use functions
            temperature=0,
            max_tokens=1000
        )
        
        message = response.choices[0].message
        
        # Handle function calls
        if message.function_call:
            function_name = message.function_call.name
            function_args = json.loads(message.function_call.arguments)
            
            # Execute the function call
            if function_name == "calculate_eta_from_duration":
                result = calculate_eta_from_duration(
                    function_args["current_time"], 
                    function_args["duration_minutes"]
                )
                # Continue conversation with function result
                # ... additional logic here
            
            # Other function handlers...
        
        # Parse final JSON response
        content = message.content or ""
        if content.startswith("{") and content.endswith("}"):
            return json.loads(content)
        else:
            # Extract JSON from response
            json_match = re.search(r"\\{[^}]+\\}", content)
            if json_match:
                return json.loads(json_match.group())
                
        return {"vehicle": "Unknown", "eta": "Unknown"}
        
    except Exception as e:
        logger.error(f"Function calling error: {e}")
        return {"vehicle": "Unknown", "eta": "Unknown"}
'''
    return code

# Test cases showing the improvements
def demonstrate_improvements():
    """Show how function calling would fix the current issues."""
    
    test_cases = [
        {
            "message": "Responding pov eta 9:15",
            "current_issue": "Returns '9:15' instead of '09:15'",
            "function_calling_fix": "validate_and_format_time('9:15') returns '09:15'",
            "result": "Properly formatted time"
        },
        {
            "message": "Responding in SAR12, ETA 57 hours", 
            "current_issue": "Shows 'in 1376m / 02:13' (wrong calculation)",
            "function_calling_fix": "validate_realistic_eta(3420) flags as unrealistic",
            "result": "AI warns about unrealistic ETA or asks for clarification"
        },
        {
            "message": "Responding pov arriving at 24:30hrs",
            "current_issue": "Shows '24:30' (invalid time)",
            "function_calling_fix": "validate_and_format_time('24:30') returns '00:30' with next_day flag",
            "result": "Properly converted to valid time"
        }
    ]
    
    print("=== How Function Calling Fixes Current Issues ===\\n")
    
    for i, case in enumerate(test_cases, 1):
        print(f"{i}. Message: {case['message']}")
        print(f"   Current Issue: {case['current_issue']}")
        print(f"   Function Calling Fix: {case['function_calling_fix']}")
        print(f"   Result: {case['result']}\\n")

if __name__ == "__main__":
    demonstrate_improvements()
    
    print("=== Implementation Benefits ===")
    print("✅ Eliminates post-processing bugs in convert_eta_to_timestamp()")
    print("✅ AI validates calculations using tools")
    print("✅ Consistent time formatting (always HH:MM)")
    print("✅ Detects unrealistic ETAs (>24 hours)")
    print("✅ Handles edge cases (24:30 → 00:30)")
    print("✅ Semantic understanding + mathematical accuracy")
    print("✅ Easy to extend with new calculation functions")
    
    print("\\n=== Next Steps ===")
    print("1. Update Azure OpenAI client to support function calling")
    print("2. Implement the calculation functions")
    print("3. Update the extract_details_from_text function")
    print("4. Add comprehensive tests for all edge cases")
    print("5. Deploy and monitor for improvements")
