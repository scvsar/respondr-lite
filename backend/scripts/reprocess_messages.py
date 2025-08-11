import os
import sys
import json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from main import extract_details_from_text, calculate_eta_info, APP_TZ, load_messages, save_messages, messages
from datetime import datetime

def reprocess_all():
    load_messages()
    updated = 0
    for m in messages:
        # Use original timestamp for context
        ts = m.get('timestamp')
        if ts:
            try:
                # Support both ISO and 'YYYY-MM-DD HH:MM:SS'
                if 'T' not in ts and ' ' in ts:
                    ts = ts.replace(' ', 'T')
                dt = datetime.fromisoformat(ts)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=APP_TZ)
            except Exception:
                dt = datetime.now(APP_TZ)
        else:
            dt = datetime.now(APP_TZ)
        # Reparse using latest logic
        parsed = extract_details_from_text(f"Sender: {m.get('name','Unknown')}. Message: {m.get('text','')}", base_time=dt)
        eta_info = calculate_eta_info(parsed.get('eta', 'Unknown'), dt)
        # Update fields
        m['vehicle'] = parsed.get('vehicle', 'Unknown')
        m['eta'] = parsed.get('eta', 'Unknown')
        m['eta_timestamp'] = eta_info.get('eta_timestamp')
        m['eta_timestamp_utc'] = eta_info.get('eta_timestamp_utc')
        m['minutes_until_arrival'] = eta_info.get('minutes_until_arrival')
        m['arrival_status'] = eta_info.get('status')
        updated += 1
    save_messages()
    print(f"Reprocessed {updated} messages.")

if __name__ == "__main__":
    reprocess_all()
