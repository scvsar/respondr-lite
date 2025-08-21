"""
Direct test of hostname redirect middleware function.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from fastapi import Request
from fastapi.responses import RedirectResponse


def test_hostname_redirect_middleware_direct():
    """Test the middleware function directly."""
    # Import the middleware function
    from app import hostname_redirect_middleware
    
    # Mock a request with legacy hostname
    request = MagicMock(spec=Request)
    request.headers = {"host": "legacy.test.com"}
    request.url.path = "/dashboard"
    request.url.query = "tab=current&status=responding"
    
    # Mock the call_next function
    call_next = AsyncMock()
    call_next.return_value = MagicMock(status_code=200)
    
    # Test with no legacy hostnames configured (default)
    import app
    original_primary = app.PRIMARY_HOSTNAME
    original_legacy = app.LEGACY_HOSTNAMES
    
    try:
        # Set up test configuration
        app.PRIMARY_HOSTNAME = "primary.test.com"
        app.LEGACY_HOSTNAMES = ["legacy.test.com", "old.test.com"]
        
        # Run the middleware
        async def run_middleware():
            return await hostname_redirect_middleware(request, call_next)
        
        # Execute the async function
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(run_middleware())
        loop.close()
        
        # Check the result
        print(f"Middleware result type: {type(result)}")
        print(f"Middleware result: {result}")
        
        # Should be a RedirectResponse
        assert isinstance(result, RedirectResponse)
        assert result.status_code == 301
        
        # Check the redirect URL
        expected_url = "https://primary.test.com/dashboard?tab=current&status=responding"
        assert result.headers["location"] == expected_url
        
        print("✓ Direct middleware test passed!")
        
    finally:
        # Restore original values
        app.PRIMARY_HOSTNAME = original_primary
        app.LEGACY_HOSTNAMES = original_legacy


def test_hostname_redirect_middleware_no_redirect():
    """Test middleware when no redirect should occur."""
    from app import hostname_redirect_middleware
    
    # Mock a request with primary hostname
    request = MagicMock(spec=Request)
    request.headers = {"host": "primary.test.com"}
    
    # Mock the call_next function
    call_next = AsyncMock()
    expected_response = MagicMock(status_code=200)
    call_next.return_value = expected_response
    
    import app
    original_primary = app.PRIMARY_HOSTNAME
    original_legacy = app.LEGACY_HOSTNAMES
    
    try:
        # Set up test configuration
        app.PRIMARY_HOSTNAME = "primary.test.com"
        app.LEGACY_HOSTNAMES = ["legacy.test.com"]
        
        # Run the middleware
        async def run_middleware():
            return await hostname_redirect_middleware(request, call_next)
        
        # Execute the async function
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(run_middleware())
        loop.close()
        
        # Should pass through to the next handler
        assert result == expected_response
        assert result.status_code == 200
        
        # Verify call_next was called
        call_next.assert_called_once_with(request)
        
        print("✓ No redirect test passed!")
        
    finally:
        # Restore original values
        app.PRIMARY_HOSTNAME = original_primary
        app.LEGACY_HOSTNAMES = original_legacy


def test_hostname_redirect_case_insensitive():
    """Test that hostname matching is case insensitive."""
    from app import hostname_redirect_middleware
    
    # Test with uppercase hostname
    request = MagicMock(spec=Request)
    request.headers = {"host": "LEGACY.TEST.COM"}
    request.url.path = "/"
    request.url.query = ""
    
    call_next = AsyncMock()
    
    import app
    original_primary = app.PRIMARY_HOSTNAME
    original_legacy = app.LEGACY_HOSTNAMES
    
    try:
        app.PRIMARY_HOSTNAME = "primary.test.com"
        app.LEGACY_HOSTNAMES = ["legacy.test.com"]
        
        async def run_middleware():
            return await hostname_redirect_middleware(request, call_next)
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(run_middleware())
        loop.close()
        
        # Should redirect despite case difference
        assert isinstance(result, RedirectResponse)
        assert result.status_code == 301
        assert result.headers["location"] == "https://primary.test.com/"
        
        print("✓ Case insensitive test passed!")
        
    finally:
        app.PRIMARY_HOSTNAME = original_primary
        app.LEGACY_HOSTNAMES = original_legacy


if __name__ == "__main__":
    test_hostname_redirect_middleware_direct()
    test_hostname_redirect_middleware_no_redirect()
    test_hostname_redirect_case_insensitive()
    print("All direct middleware tests passed!")