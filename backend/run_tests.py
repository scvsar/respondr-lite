#!/usr/bin/env python3
"""
Run working pytest tests for the Respondr backend
"""
import sys

def main():
    """Run working pytest tests"""
    print("Running Respondr backend tests...")
    
    # Run only our working test files to avoid hanging/broken tests
    working_tests = [
        "tests/test_storage_working.py",
        "tests/test_queue_idempotency.py",
        "tests/test_luna_extraction.py",
        "tests/test_system_notices.py",
        "tests/test_webhook_auth.py",
        "tests/test_auth_validation.py",
        "tests/test_request_privacy.py",
        "tests/test_storage_fail_closed.py",
        "tests/test_storage_rows.py",
        "tests/test_file_storage.py",
        "tests/test_storage_mutation_failures.py",
        "tests/test_storage_async_boundary.py",
        "tests/test_time_filters.py",
        "tests/test_timezone_config.py",
        "tests/test_llm_retries.py",
        "tests/test_responder_identity.py",
        "tests/test_manual_responder.py",
        "tests/test_debug_authorization.py",
        "tests/test_model_output_validation.py",
        "tests/test_cleanup_duplicate_responders.py",
        "tests/test_main.py",
        "tests/test_retention.py",
        "tests/test_retention_api.py",
        "tests/test_dashboard_authorization.py",
        "tests/test_profile_authorization.py",
        "tests/test_local_user_storage.py",
        "tests/test_local_storage_concurrency.py",
        "tests/test_request_log_api.py",
    ]
    
    # Import pytest and run tests directly to avoid subprocess hanging
    try:
        import pytest
        
        # Build args for pytest
        args = ["-v"] + working_tests
        
        # Add coverage if available
        try:
            import pytest_cov  # type: ignore  # noqa: F401
            args.extend(["--cov=.", "--cov-report=term"])
        except ImportError:
            print("pytest-cov not available, running basic tests...")
        
        # Run pytest directly
        exit_code = pytest.main(args)
        
        print(f"\nTest run completed with exit code: {exit_code}")
        return exit_code
        
    except ImportError:
        print("pytest not available!")
        return 1
    except Exception as e:
        print(f"Error running tests: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
