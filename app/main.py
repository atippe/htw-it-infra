from datetime import datetime
from typing import List
from fastapi import FastAPI, WebSocket, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import jinja2
import requests
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
    instance_info = get_instance_metadata()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "api_version": API_VERSION,
        "instance_info": instance_info
    })


@app.get(API_PREFIX + "/messages")
async def get_messages():
    """Get all messages (initial load)"""
    instance_info = get_instance_metadata()
    return {"messages": messages
        , "instance_info": instance_info}


@app.post(API_PREFIX + "/messages")
async def create_message(message: Message):
    """Create a new message"""
    instance_info = get_instance_metadata()
    message_dict = {
        "username": message.username,
        "content": message.content,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "instance_info": instance_info
    }

    messages.append(message_dict)

    await broadcast_message(message_dict)

    return {"status": "success", "message": message_dict}


@app.websocket(API_PREFIX + "/ws/{username}")
async def websocket_endpoint(websocket: WebSocket, username: str):
    """WebSocket endpoint for real-time message updates"""
    await websocket.accept()

    # Send instance info only once at connection
    instance_info = get_instance_metadata()
    await websocket.send_json({
        "type": "connection_info",
        "instance_info": instance_info,
        "message": f"Connected to instance: {instance_info['instance_id']} in {instance_info['availability_zone']}"
    })

    active_connections.append(websocket)

    try:
        while True:
            await websocket.receive_text()
    except:
        active_connections.remove(websocket)
        await websocket.close()


def get_instance_metadata():
    try:
        # AWS EC2 instance metadata endpoint
        response = requests.get('http://169.254.169.254/latest/meta-data/instance-id', timeout=2)
        instance_id = response.text if response.status_code == 200 else 'Unknown'

        response = requests.get('http://169.254.169.254/latest/meta-data/placement/availability-zone', timeout=2)
        az = response.text if response.status_code == 200 else 'Unknown'

        return {
            'instance_id': instance_id,
            'availability_zone': az
        }
    except:
        return {
            'instance_id': 'Unknown',
            'availability_zone': 'Unknown'
        }
