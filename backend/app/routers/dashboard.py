"""Dashboard and static file endpoints."""

import os
from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, FileResponse
from typing import List, Dict, Any

from ..utils import esc_html
from ..storage import get_messages, get_deleted_messages

router = APIRouter()


def generate_dashboard_html(messages: List[Dict[str, Any]], title: str = "Responder Dashboard") -> str:
    """Generate the dashboard HTML from messages."""
    
    def format_minutes(minutes):
        """Format minutes for display."""
        if minutes is None:
            return "Unknown"
        
        # Handle string values - convert to int
        try:
            minutes_int = int(minutes)
        except (ValueError, TypeError):
            return "Unknown"
            
        if minutes_int <= 0:
            return "Arrived"
        if minutes_int < 60:
            return f"{minutes_int} min"
        hours = minutes_int // 60
        remaining_minutes = minutes_int % 60
        if remaining_minutes == 0:
            return f"{hours} hr"
        return f"{hours}h {remaining_minutes}m"

    # Generate table rows
    rows = []
    for msg in messages:
        status_class = ""
        if msg.get("arrival_status") == "Arrived":
            status_class = "arrived"
        elif msg.get("arrival_status") == "Overdue":
            status_class = "overdue"

        rows.append(f"""
        <tr class="{status_class}">
            <td>{esc_html(msg.get('timestamp', ''))}</td>
            <td>{esc_html(msg.get('name', ''))}</td>
            <td>{esc_html(msg.get('vehicle', ''))}</td>
            <td>{esc_html(msg.get('eta', ''))}</td>
            <td>{esc_html(msg.get('eta_timestamp', ''))}</td>
            <td>{format_minutes(msg.get('minutes_until_arrival'))}</td>
            <td class="status-{msg.get('arrival_status', 'unknown').lower()}">{esc_html(msg.get('arrival_status', ''))}</td>
        </tr>
        """)

    table_content = "".join(rows) if rows else '<tr><td colspan="7">No active responders</td></tr>'

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>{esc_html(title)}</title>
        <meta http-equiv="refresh" content="30">
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; }}
            table {{ border-collapse: collapse; width: 100%; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            th {{ background-color: #f2f2f2; }}
            .arrived {{ background-color: #d4edda; }}
            .overdue {{ background-color: #f8d7da; }}
            .status-arrived {{ color: green; font-weight: bold; }}
            .status-overdue {{ color: red; font-weight: bold; }}
            .status-responding {{ color: blue; }}
        </style>
    </head>
    <body>
        <h1>{esc_html(title)}</h1>
        <p>Last updated: <span id="timestamp">{esc_html(str(__import__('datetime').datetime.now()))}</span></p>
        <table>
            <thead>
                <tr>
                    <th>Timestamp</th>
                    <th>Name</th>
                    <th>Vehicle</th>
                    <th>ETA</th>
                    <th>ETA Timestamp</th>
                    <th>Time Until</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
                {table_content}
            </tbody>
        </table>
    </body>
    </html>
    """


@router.get("/dashboard", response_class=HTMLResponse)
def get_dashboard():
    """Serve the main dashboard HTML."""
    messages = get_messages()
    return HTMLResponse(content=generate_dashboard_html(messages, "Responder Dashboard"))


@router.get("/deleted-dashboard", response_class=HTMLResponse)
def get_deleted_dashboard():
    """Serve the deleted messages dashboard HTML."""
    messages = get_deleted_messages()
    return HTMLResponse(content=generate_dashboard_html(messages, "Deleted Messages Dashboard"))