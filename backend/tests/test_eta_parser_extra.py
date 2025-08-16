from datetime import datetime, timezone
import re

from main import convert_eta_text_to_hhmm


BASE = datetime(2024, 2, 22, 6, 45, tzinfo=timezone.utc)


def test_arrive_in_no_units():
    assert convert_eta_text_to_hhmm("be there in 20", BASE) == "07:05"


def test_avoid_vehicle_minutes_confusion():
    # Should not interpret "coming in 78" as minutes; 2330 wins
    assert convert_eta_text_to_hhmm("responding in 78 should arrive 2330", BASE, "21:40") == "23:30"


def test_pushed_back_words_against_prev():
    assert convert_eta_text_to_hhmm("pushed back by fifteen", BASE, "21:40") == "21:55"
