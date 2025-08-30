"""
Enhanced test suite for LLM processing functionality.

Tests Azure OpenAI integration, vehicle normalization, ETA parsing, and error handling.
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta
from app.llm import extract_details_from_text, _call_llm_only, _normalize_vehicle_name
from app.config import APP_TZ


class TestVehicleNormalization:
    """Test vehicle name normalization functionality."""

    def test_pov_normalization(self):
        """Test POV variations are normalized correctly."""
        test_cases = [
            "POV", "pov", "Pov", "P.O.V", "p.o.v",
            "personal vehicle", "Personal Vehicle", "PERSONAL VEHICLE",
            "personal", "Personal", "PERSONAL",
            "own vehicle", "Own Vehicle", "my vehicle", "My Vehicle"
        ]
        
        for test_input in test_cases:
            result = _normalize_vehicle_name(test_input)
            assert result == "POV", f"Failed to normalize '{test_input}' to POV"

    def test_sar_vehicle_normalization(self):
        """Test SAR vehicle variations are normalized correctly."""
        test_cases = [
            ("SAR78", "SAR-78"),
            ("SAR-78", "SAR-78"),
            ("sar78", "SAR-78"),
            ("sar-78", "SAR-78"),
            ("SAR 78", "SAR-78"),
            ("SAR7", "SAR-7"),
            ("SAR-7", "SAR-7"),
            ("sar7", "SAR-7"),
            ("SAR 7", "SAR-7")
        ]
        
        for test_input, expected in test_cases:
            result = _normalize_vehicle_name(test_input)
            assert result == expected, f"Failed to normalize '{test_input}' to '{expected}', got '{result}'"

    def test_vehicle_name_edge_cases(self):
        """Test edge cases in vehicle name normalization."""
        test_cases = [
            ("", ""),
            (None, ""),
            ("   ", ""),
            ("SAR-", "SAR-"),
            ("SAR", "SAR"),
            ("123", "123"),
            ("Unknown", "Unknown"),
            ("Not Responding", "Not Responding")
        ]
        
        for test_input, expected in test_cases:
            result = _normalize_vehicle_name(test_input)
            assert result == expected, f"Failed to handle edge case '{test_input}'"

    def test_complex_vehicle_names(self):
        """Test complex vehicle name variations."""
        test_cases = [
            ("SAR-78 Truck", "SAR-78"),
            ("Unit SAR-7", "SAR-7"),
            ("Team SAR78", "SAR-78"),
            ("Vehicle SAR 7", "SAR-7"),
            ("I'll take POV", "POV"),
            ("Taking my personal vehicle", "POV"),
            ("Using SAR78 today", "SAR-78")
        ]
        
        for test_input, expected in test_cases:
            result = _normalize_vehicle_name(test_input)
            assert result == expected, f"Failed to extract '{expected}' from '{test_input}', got '{result}'"


class TestLLMTextExtraction:
    """Test LLM text extraction and parsing functionality."""

    def test_extract_details_basic_functionality(self):
        """Test basic LLM extraction functionality."""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content='{"vehicle": "SAR-78", "eta": "15 minutes", "confidence": 0.9}'
                )
            )
        ]
        
        with patch('app.llm.client') as mock_client:
            mock_client.chat.completions.create.return_value = mock_response
            
            result = extract_details_from_text("I'll take SAR78, ETA 15 minutes")
            
            assert result["vehicle"] == "SAR-78"
            assert result["eta"] == "15 minutes"
            assert result["confidence"] == 0.9

    def test_extract_details_with_function_calling(self):
        """Test LLM extraction with function calling format."""
        mock_response = MagicMock()
        mock_function_call = MagicMock()
        mock_function_call.name = "extract_sar_details"
        mock_function_call.arguments = '{"vehicle": "POV", "eta": "30 minutes", "confidence": 0.85}'
        
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content=None,
                    function_call=mock_function_call
                )
            )
        ]
        
        with patch('app.llm.client') as mock_client:
            mock_client.chat.completions.create.return_value = mock_response
            
            result = extract_details_from_text("Taking my POV, will be there in 30 minutes")
            
            assert result["vehicle"] == "POV"
            assert result["eta"] == "30 minutes"
            assert result["confidence"] == 0.85

    def test_extract_details_eta_time_conversion(self):
        """Test ETA time conversion and computation."""
        # Test relative time
        base_time = datetime.now(APP_TZ)
        
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content='{"vehicle": "SAR-7", "eta": "20 minutes", "confidence": 0.9}'
                )
            )
        ]
        
        with patch('app.llm.client') as mock_client:
            mock_client.chat.completions.create.return_value = mock_response
            
            result = extract_details_from_text("SAR-7 responding, 20 minutes out", base_time=base_time)
            
            assert "eta_timestamp" in result
            assert "eta_minutes" in result
            assert result["eta_minutes"] == 20
            
            # Check that eta_timestamp is approximately base_time + 20 minutes
            eta_dt = datetime.fromisoformat(result["eta_timestamp"].replace('Z', '+00:00'))
            expected_eta = base_time + timedelta(minutes=20)
            time_diff = abs((eta_dt - expected_eta).total_seconds())
            assert time_diff < 60  # Within 1 minute tolerance

    def test_extract_details_absolute_time_parsing(self):
        """Test absolute time parsing in ETA."""
        base_time = datetime(2025, 1, 15, 14, 30, 0, tzinfo=APP_TZ)
        
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content='{"vehicle": "POV", "eta": "15:00", "confidence": 0.8}'
                )
            )
        ]
        
        with patch('app.llm.client') as mock_client:
            mock_client.chat.completions.create.return_value = mock_response
            
            result = extract_details_from_text("POV, will arrive at 3:00 PM", base_time=base_time)
            
            assert "eta_timestamp" in result
            assert "eta_minutes" in result
            
            # Should compute minutes from base_time to 15:00 (3:00 PM)
            expected_minutes = 30  # 14:30 to 15:00 = 30 minutes
            assert result["eta_minutes"] == expected_minutes

    def test_extract_details_error_handling(self):
        """Test error handling in LLM extraction."""
        # Test API error
        with patch('app.llm.client') as mock_client:
            mock_client.chat.completions.create.side_effect = Exception("API Error")
            
            result = extract_details_from_text("SAR-78 responding")
            
            assert result["vehicle"] == ""
            assert result["eta"] == ""
            assert result["confidence"] == 0.0
            assert "error" in result

    def test_extract_details_malformed_json_response(self):
        """Test handling of malformed JSON responses from LLM."""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content='malformed json response'
                )
            )
        ]
        
        with patch('app.llm.client') as mock_client:
            mock_client.chat.completions.create.return_value = mock_response
            
            result = extract_details_from_text("SAR-78 responding, 15 minutes")
            
            # Should fall back to empty values on JSON parse error
            assert result["vehicle"] == ""
            assert result["eta"] == ""
            assert result["confidence"] == 0.0

    def test_extract_details_partial_information(self):
        """Test extraction when only partial information is available."""
        test_cases = [
            # Only vehicle, no ETA
            ('{"vehicle": "SAR-78", "eta": "", "confidence": 0.7}', "SAR-78", ""),
            # Only ETA, no vehicle
            ('{"vehicle": "", "eta": "25 minutes", "confidence": 0.6}', "", "25 minutes"),
            # No information
            ('{"vehicle": "", "eta": "", "confidence": 0.1}', "", "")
        ]
        
        for json_content, expected_vehicle, expected_eta in test_cases:
            mock_response = MagicMock()
            mock_response.choices = [
                MagicMock(
                    message=MagicMock(content=json_content)
                )
            ]
            
            with patch('app.llm.client') as mock_client:
                mock_client.chat.completions.create.return_value = mock_response
                
                result = extract_details_from_text("Test message")
                
                assert result["vehicle"] == expected_vehicle
                assert result["eta"] == expected_eta

    def test_extract_details_confidence_scoring(self):
        """Test confidence scoring in LLM responses."""
        test_cases = [
            ('{"vehicle": "SAR-78", "eta": "15 minutes", "confidence": 0.95}', 0.95),
            ('{"vehicle": "POV", "eta": "uncertain", "confidence": 0.3}', 0.3),
            ('{"vehicle": "", "eta": "", "confidence": 0.0}', 0.0)
        ]
        
        for json_content, expected_confidence in test_cases:
            mock_response = MagicMock()
            mock_response.choices = [
                MagicMock(
                    message=MagicMock(content=json_content)
                )
            ]
            
            with patch('app.llm.client') as mock_client:
                mock_client.chat.completions.create.return_value = mock_response
                
                result = extract_details_from_text("Test message")
                
                assert result["confidence"] == expected_confidence


class TestLLMIntegration:
    """Test LLM client integration and configuration."""

    def test_llm_client_initialization(self):
        """Test that LLM client is properly initialized."""
        from app.llm import client
        assert client is not None

    def test_llm_call_with_proper_parameters(self):
        """Test that LLM calls are made with proper parameters."""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content='{"vehicle": "SAR-78", "eta": "15 minutes", "confidence": 0.9}'
                )
            )
        ]
        
        with patch('app.llm.client') as mock_client:
            mock_client.chat.completions.create.return_value = mock_response
            
            extract_details_from_text("Test message")
            
            # Verify the API call was made with expected parameters
            mock_client.chat.completions.create.assert_called_once()
            call_args = mock_client.chat.completions.create.call_args
            
            # Check that required parameters are present
            assert 'model' in call_args[1]
            assert 'messages' in call_args[1]
            assert call_args[1]['temperature'] == 0.1  # Should use low temperature for consistency

    def test_llm_retry_logic(self):
        """Test retry logic for LLM API calls."""
        # First call fails, second succeeds
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content='{"vehicle": "SAR-78", "eta": "15 minutes", "confidence": 0.9}'
                )
            )
        ]
        
        with patch('app.llm.client') as mock_client:
            # First call raises exception, second succeeds
            mock_client.chat.completions.create.side_effect = [
                Exception("Temporary API error"),
                mock_response
            ]
            
            result = extract_details_from_text("SAR-78 responding, 15 minutes")
            
            # Should have retried and succeeded
            assert result["vehicle"] == "SAR-78"
            assert result["eta"] == "15 minutes"
            assert mock_client.chat.completions.create.call_count == 2


class TestRealWorldScenarios:
    """Test real-world message parsing scenarios."""

    def test_typical_sar_messages(self):
        """Test parsing of typical SAR response messages."""
        test_messages = [
            "SAR-78 responding, ETA 20 minutes",
            "I'll take POV, be there in 15",
            "Unit 7 en route, 25 min out",
            "Personal vehicle, arriving at 2:30 PM",
            "SAR78 delayed, now 45 minutes",
            "POV responding, 10-15 minutes"
        ]
        
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content='{"vehicle": "SAR-78", "eta": "20 minutes", "confidence": 0.9}'
                )
            )
        ]
        
        with patch('app.llm.client') as mock_client:
            mock_client.chat.completions.create.return_value = mock_response
            
            for message in test_messages:
                result = extract_details_from_text(message)
                
                # Should return valid structure for all messages
                assert "vehicle" in result
                assert "eta" in result
                assert "confidence" in result
                assert isinstance(result["confidence"], (int, float))

    def test_ambiguous_messages(self):
        """Test parsing of ambiguous or unclear messages."""
        ambiguous_messages = [
            "Maybe responding if available",
            "Not sure about timing",
            "Depends on traffic",
            "Will try to make it",
            "Running late but coming"
        ]
        
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content='{"vehicle": "", "eta": "", "confidence": 0.2}'
                )
            )
        ]
        
        with patch('app.llm.client') as mock_client:
            mock_client.chat.completions.create.return_value = mock_response
            
            for message in ambiguous_messages:
                result = extract_details_from_text(message)
                
                # Should handle ambiguous messages gracefully
                assert "confidence" in result
                assert result["confidence"] <= 0.5  # Low confidence for ambiguous messages

    def test_non_response_messages(self):
        """Test parsing of messages that aren't responses."""
        non_response_messages = [
            "Thanks for the update",
            "Good luck everyone",
            "Stay safe out there",
            "Weather looks good",
            "Radio check"
        ]
        
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content='{"vehicle": "", "eta": "", "confidence": 0.0}'
                )
            )
        ]
        
        with patch('app.llm.client') as mock_client:
            mock_client.chat.completions.create.return_value = mock_response
            
            for message in non_response_messages:
                result = extract_details_from_text(message)
                
                # Should recognize non-response messages
                assert result["confidence"] == 0.0
                assert result["vehicle"] == ""
                assert result["eta"] == ""


class TestLLMPerformance:
    """Test LLM performance and timeout handling."""

    def test_llm_timeout_handling(self):
        """Test handling of LLM API timeouts."""
        import time
        
        def slow_api_call(*args, **kwargs):
            time.sleep(0.1)  # Simulate slow response
            raise Exception("Timeout")
        
        with patch('app.llm.client') as mock_client:
            mock_client.chat.completions.create.side_effect = slow_api_call
            
            start_time = time.time()
            result = extract_details_from_text("Test message")
            end_time = time.time()
            
            # Should handle timeout gracefully and not hang
            assert end_time - start_time < 5.0  # Should not take more than 5 seconds
            assert result["vehicle"] == ""
            assert result["eta"] == ""
            assert "error" in result

    def test_llm_large_message_handling(self):
        """Test handling of very large messages."""
        large_message = "This is a very long message. " * 1000  # Very long text
        
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content='{"vehicle": "", "eta": "", "confidence": 0.1}'
                )
            )
        ]
        
        with patch('app.llm.client') as mock_client:
            mock_client.chat.completions.create.return_value = mock_response
            
            result = extract_details_from_text(large_message)
            
            # Should handle large messages without crashing
            assert "vehicle" in result
            assert "eta" in result
            assert "confidence" in result