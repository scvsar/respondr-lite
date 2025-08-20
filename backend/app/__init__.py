from fastapi import FastAPI

from .routers import webhook, responders, dashboard, acr, user

app = FastAPI()
app.include_router(webhook.router)
app.include_router(responders.router)
app.include_router(dashboard.router)
app.include_router(acr.router)
app.include_router(user.router)
