from datetime import datetime
from typing import List
from fastapi import FastAPI, WebSocket, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import jinja2
from pydantic import BaseModel

API_VERSION = "v2"
API_PREFIX = f"/api/{API_VERSION}"

VERSION = "0.1.0"
app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/assets", StaticFiles(directory="assets"), name="assets")

messages = []
active_connections: List[WebSocket] = []


class Message(BaseModel):
    username: str
    content: str


async def broadcast_message(message: dict):
    for connection in active_connections:
        await connection.send_json(message)


@app.get("/")
async def home(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "api_version": API_VERSION
    })


@app.get(API_PREFIX + "/messages")
async def get_messages():
    """Get all messages (initial load)"""
    return {"messages": messages}


@app.post(API_PREFIX + "/messages")
async def create_message(message: Message):
    """Create a new message"""
    message_dict = {
        "username": message.username,
        "content": message.content,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    messages.append(message_dict)

    await broadcast_message(message_dict)

    return {"status": "success", "message": message_dict}


@app.websocket(API_PREFIX + "/ws/{username}")
async def websocket_endpoint(websocket: WebSocket, username: str):
    """WebSocket endpoint for real-time message updates"""
    await websocket.accept()
    active_connections.append(websocket)

    try:
        while True:
            await websocket.receive_text()
    except:
        active_connections.remove(websocket)
        await websocket.close()
