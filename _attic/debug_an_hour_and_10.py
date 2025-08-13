"""
Quick local test for "an hour and 10" parsing
"""

import sys
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv('backend/.env')

current_dir = os.path.dirname(os.path.abspath(__file__))
backend_path = os.path.join(current_dir, 'backend')
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from main import extract_details_from_text

def run():
    base = datetime(2025, 8, 11, 13, 46, 21)
    messages = [
        ("Sender: Randy Treit. Message: Actually I’ll be an hour and 10 min", "14:56"),
        ("Sender: Randy Treit. Message: an hour and 10 minutes", "14:56"),
        ("Sender: Randy Treit. Message: 1 hour and 10 minutes", "14:56"),
        ("Sender: Randy Treit. Message: 2 hours and 5 minutes", "15:51"),
        ("Sender: Randy Treit. Message: half an hour", "14:16"),
    ]
    for msg, expected in messages:
        res = extract_details_from_text(msg, base_time=base)
        print(f"{msg} -> {res.get('eta')} (expected {expected}) | full: {res}")

if __name__ == "__main__":
    run()
