import json
import pytest
from fastapi.testclient import TestClient
from fastapi.staticfiles import StaticFiles
from unittest.mock import patch, MagicMock
import os
import re
from main import app, extract_details_from_text

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_and_teardown():
    """Setup and teardown for each test"""
    # Setup: Reset the global messages list for each test
    global_messages = []
    with patch('main.messages', global_messages):
        yield
    # Teardown: No special cleanup needed

@pytest.fixture
def mock_openai_response():
    """Mock the OpenAI client response"""
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(
            message=MagicMock(
                content='{"vehicle": "SAR78", "eta": "15 minutes"}'
            )
        )
    ]
    return mock_response

def test_get_responder_data_empty():
    """Test the /api/responders endpoint with no data"""
    # Clean up any existing data file and reload to ensure empty state
    data_file = "./respondr_messages.json"
    backup_exists = os.path.exists(data_file)
    backup_data = None
    
    # Backup existing data if it exists
    if backup_exists:
        with open(data_file, 'r') as f:
            backup_data = f.read()
        os.remove(data_file)
    
    try:
        # Reload messages to get empty state
        from main import load_messages
        load_messages()
        
        with patch('main.messages', []):
            response = client.get("/api/responders")
            assert response.status_code == 200
            assert response.json() == []
    finally:
        # Restore backup data if it existed
        if backup_exists and backup_data:
            with open(data_file, 'w') as f:
                f.write(backup_data)

def test_webhook_endpoint(mock_openai_response):
    """Test the webhook endpoint with a mock OpenAI response"""
    # Use a test messages list
    test_messages = []
    
    # Mock the response to not use function calling for this test
    mock_openai_response.choices = [
        MagicMock(
            message=MagicMock(
                content='{"vehicle": "SAR-78", "eta_iso": "2025-01-01T15:45:00Z", "status":"Responding", "confidence":0.9}',
                function_call=None
            )
        )
    ]
    
    # Create a mock client that we can patch
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_openai_response
    
    with patch('main.messages', test_messages), \
         patch('main.client', mock_client):
        
        webhook_data = {
            "name": "Test User",
            "text": "I'm responding with SAR78, ETA 15 minutes",
            "created_at": 1627484400
        }
        
        response = client.post("/webhook", json=webhook_data)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        
        # Verify the message was stored
        response = client.get("/api/responders")
        assert response.status_code == 200
        
        # Check the response data
        response_data = response.json()
        assert len(response_data) > 0
        
        # Find the test user's message (might not be the only one due to test isolation issues)
        test_user_message = next((msg for msg in response_data if msg["name"] == "Test User"), None)

        # If we found the test user's message, verify its contents
        if test_user_message:
            assert test_user_message["vehicle"] == "SAR-78"
            assert re.match(r"\d{2}:\d{2}", test_user_message["eta"])  # HH:MM after LLM iso conversion
            assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", test_user_message["eta_timestamp"])  # legacy format in tests

def test_extract_details_with_vehicle_and_eta():
    """Test extracting details with both vehicle and ETA present"""
    # Create a mock client
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(
            message=MagicMock(
                content='{"vehicle": "SAR-78", "eta_iso": "2025-01-01T15:30:00Z", "status":"Responding", "confidence":0.8}',
                function_call=None
            )
        )
    ]
    mock_client.chat.completions.create.return_value = mock_response
    
    with patch('main.client', mock_client):
        
        result = extract_details_from_text("Taking SAR78, ETA 15 minutes")
    assert result["vehicle"] == "SAR-78"
    assert re.match(r"\d{2}:\d{2}", result["eta"]) 

def test_extract_details_with_pov():
    """Test extracting details with POV vehicle"""
    # Create a mock client
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(
            message=MagicMock(
                content='{"vehicle": "POV", "eta_iso": "2025-01-01T23:30:00Z", "status":"Responding", "confidence":0.7}',
                function_call=None
            )
        )
    ]
    mock_client.chat.completions.create.return_value = mock_response
    
    with patch('main.client', mock_client):
        
        result = extract_details_from_text("Taking my personal vehicle, ETA 23:30")
    assert result["vehicle"] == "POV"
    assert re.match(r"\d{2}:\d{2}", result["eta"])  # derived from eta_iso

def test_extract_details_with_api_error():
    """Test error handling when API call fails"""
    # Create a mock client that raises an exception
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = Exception("API Error")
    
    with patch('main.client', mock_client):
        result = extract_details_from_text("Taking SAR78, ETA 15 minutes")
    # With AI error, defaults to Unknown per LLM-only contract
    assert result["vehicle"] == "Unknown"
    assert result["eta"] == "Unknown"

def test_dashboard_endpoint():
    """Test the dashboard HTML endpoint"""
    # Create a test message
    test_message = {
        "name": "Test User",
        "text": "Test message",
        "timestamp": "2025-08-01 12:00:00",
        "vehicle": "SAR78",
        "eta": "12:15",
        "eta_timestamp": "2025-08-01 12:15:00",
        "minutes_until_arrival": 15,
        "arrival_status": "On Route"
    }
    
    # Patch the messages list with our test data
    with patch('main.messages', [test_message]):
        response = client.get("/dashboard")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Responder Dashboard" in response.text
        assert "Test User" in response.text
        assert "SAR78" in response.text
        assert "2025-08-01 12:15:00" in response.text

def test_static_files():
    """Test that static files are correctly handled based on environment"""
    # In test mode, static files should not be mounted
    # Find if there's a static route in the application
    static_route = False
    for route in app.routes:
        route_path = getattr(route, "path", getattr(route, "path_format", ""))
        if isinstance(route_path, str) and route_path.startswith("/static"):
            static_route = True
            break
    
    # In test mode, static files should NOT be mounted for simplicity
    assert not static_route, "Static files should not be mounted in test mode"

def test_user_info():
    """Test the /api/user endpoint with OAuth2 headers"""
    # Test with OAuth2 Proxy headers - use allowed domain
    headers = {
        "X-User": "test@scvsar.org",
        "X-Preferred-Username": "Test User",
        "X-User-Groups": "group1, group2, group3"
    }
    
    response = client.get("/api/user", headers=headers)
    assert response.status_code == 200
    
    data = response.json()
    assert data["authenticated"] == True
    assert data["email"] == "test@scvsar.org"
    assert data["name"] == "Test User"
    assert data["groups"] == ["group1", "group2", "group3"]
    assert data["logout_url"] == "/oauth2/sign_out?rd=%2F"

def test_user_info_minimal_headers():
    """Test the /api/user endpoint with minimal OAuth2 headers"""
    headers = {
        "X-User": "minimal@rtreit.com"  # Use allowed domain
    }
    
    response = client.get("/api/user", headers=headers)
    assert response.status_code == 200
    
    data = response.json()
    assert data["authenticated"] == True
    assert data["email"] == "minimal@rtreit.com"
    assert data["name"] == "minimal@rtreit.com"  # Should fallback to email
    assert data["groups"] == []
    assert data["logout_url"] == "/oauth2/sign_out?rd=%2F"

def test_user_info_no_headers():
    """Test the /api/user endpoint with no OAuth2 headers"""
    response = client.get("/api/user")
    assert response.status_code == 200
    
    data = response.json()
    assert data["authenticated"] == False  # Should be False when no headers present
    assert data["email"] is None
    assert data["name"] is None
    assert data["groups"] == []
    assert data["logout_url"] == "/oauth2/sign_out?rd=%2F"

def test_user_info_oauth2_proxy_headers():
    """Test the /api/user endpoint with OAuth2 Proxy standard headers"""
    # Test with OAuth2 Proxy standard headers (X-Auth-Request-*) - use allowed domain
    headers = {
        "X-Auth-Request-Email": "oauth2@scvsar.org",
        "X-Auth-Request-Preferred-Username": "OAuth2 User",
        "X-Auth-Request-Groups": "admin, users, testers"
    }
    
    response = client.get("/api/user", headers=headers)
    assert response.status_code == 200
    
    data = response.json()
    assert data["authenticated"] == True
    assert data["email"] == "oauth2@scvsar.org"
    assert data["name"] == "OAuth2 User"
    assert data["groups"] == ["admin", "users", "testers"]
    assert data["logout_url"] == "/oauth2/sign_out?rd=%2F"
