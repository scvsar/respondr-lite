from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard() -> str:
    import main  # type: ignore
    rows = "".join(
        f"<tr><td>{m.get('timestamp')}</td><td>{m.get('name')}</td><td>{m.get('vehicle')}</td><td>{m.get('eta_timestamp')}</td></tr>"
        for m in main.messages
    )
    return f"""
    <html><body>
    <h1>Responder Dashboard</h1>
    <table border='1'>
    <tr><th>Time</th><th>Name</th><th>Vehicle</th><th>ETA</th></tr>
    {rows}
    </table>
    </body></html>
    """
