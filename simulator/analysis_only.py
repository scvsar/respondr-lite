"""One-off helper to run post-mission analysis on an existing mission file without re-running the mission simulation.

Usage:
    python analysis_only.py missions/20250902T224514Z-mission.json
"""
import json
import sys
from datetime import datetime

from mission_simulator import MissionSimulator, now_utc


def main():
    if len(sys.argv) < 2:
        print("Usage: python analysis_only.py <mission-file.json>")
        sys.exit(2)
    path = sys.argv[1]
    with open(path, "r", encoding="utf-8") as f:
        mission = json.load(f)

    started = mission.get("started_utc")
    if not started:
        print("Mission file missing 'started_utc' field")
        sys.exit(2)
    # Parse the start time into a datetime
    try:
        start_dt = datetime.fromisoformat(started)
    except Exception:
        # Fallback: try known format
        start_dt = datetime.strptime(started[:19], "%Y-%m-%dT%H:%M:%S")

    sim = MissionSimulator(dry_run=False)
    # Call the internal analysis routine
    sim._perform_post_mission_analysis(mission, start_dt)


if __name__ == "__main__":
    main()
