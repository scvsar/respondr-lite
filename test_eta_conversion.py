import os
import sys
from datetime import datetime

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from main import convert_eta_to_timestamp


def test_convert_eta_duration_variants():
    base = datetime(2024, 1, 1, 12, 0)
    assert convert_eta_to_timestamp("30m", base) == "12:30"
    assert convert_eta_to_timestamp("2h", base) == "14:00"
    assert convert_eta_to_timestamp("1.5 hours", base) == "13:30"
    assert convert_eta_to_timestamp("in 45", base) == "12:45"
    assert convert_eta_to_timestamp("~10 mins", base) == "12:10"
