import asyncio
from datetime import datetime
from typing import List
import json
import os
import aioredis
import asyncpg
from fastapi import FastAPI, WebSocket, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import requests
from pydantic import BaseModel
from contextlib import asynccontextmanager
import logging

from starlette.websockets import WebSocketDisconnect

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_VERSION = "v2"
API_PREFIX = f"/api/{API_VERSION}"
VERSION = "0.1.0"

# Fallback in-memory storage
local_messages = []
local_connections: List[WebSocket] = []


class ChatApp:
    def __init__(self):
        self.db_pool = None
        self.redis_client = None
        self.active_connections: List[WebSocket] = []
        self.is_db_available = False
        self.is_redis_available = False

    async def startup(self):
        # Try to connect to PostgreSQL
        try:
            self.db_pool = await asyncpg.create_pool(
                user=os.getenv('DB_USERNAME'),
                password=os.getenv('DB_PASSWORD'),
                database=os.getenv('DB_NAME'),
                host=os.getenv('DB_ENDPOINT')
            )

            async with self.db_pool.acquire() as conn:
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS messages (
                        id SERIAL PRIMARY KEY,
                        username TEXT,
                        content TEXT,
                        timestamp TIMESTAMP,
                        instance_id TEXT,
                        availability_zone TEXT
                    )
                ''')
            self.is_db_available = True
            logger.info("PostgreSQL connection established")
        except Exception as e:
            logger.warning(f"PostgreSQL connection failed: {e}")
            self.is_db_available = False

        # Try to connect to Redis
        try:
            self.redis_client = aioredis.from_url(
                f"redis://{os.getenv('REDIS_ENDPOINT')}:6379",
                decode_responses=True
            )
            self.redis_client.ping()  # Test connection
            self.is_redis_available = True
            logger.info("Redis connection established")
        except Exception as e:
            logger.warning(f"Redis connection failed: {e}")
            self.is_redis_available = False

    async def broadcast_message(self, message: dict):
        if self.is_redis_available:
            try:
                await self.redis_client.publish('chat_messages', json.dumps(message))
            except Exception as e:
                logger.warning(f"Redis broadcast failed: {e}")
                await self.local_broadcast(message)
        else:
            await self.local_broadcast(message)

    async def local_broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning(f"WebSocket send failed: {e}")

    async def save_message(self, message_dict: dict):
        if self.is_db_available:
            try:
                async with self.db_pool.acquire() as conn:
                    await conn.execute('''
                        INSERT INTO messages (username, content, timestamp, instance_id, availability_zone)
                        VALUES ($1, $2, $3, $4, $5)
                    ''', message_dict['username'], message_dict['content'],
                                       datetime.strptime(message_dict['timestamp'], "%Y-%m-%d %H:%M:%S"),
                                       message_dict['instance_info']['instance_id'],
                                       message_dict['instance_info']['availability_zone'])
            except Exception as e:
                logger.warning(f"Database save failed: {e}")
                local_messages.append(message_dict)
        else:
            local_messages.append(message_dict)

    async def get_messages(self):
        if self.is_db_available:
            try:
                async with self.db_pool.acquire() as conn:
                    rows = await conn.fetch('''
                        SELECT username, content, timestamp, instance_id, availability_zone 
                        FROM messages 
                        ORDER BY timestamp DESC 
                        LIMIT 100
                    ''')
                    return [dict(row) for row in rows]
            except Exception as e:
                logger.warning(f"Database fetch failed: {e}")
                return local_messages
        return local_messages


@asynccontextmanager
async def lifespan(app: FastAPI):
    await chat_app.startup()
    yield
    if chat_app.db_pool:
        await chat_app.db_pool.close()


chat_app = ChatApp()
app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory="templates")
app.mount("/assets", StaticFiles(directory="assets"), name="assets")


class Message(BaseModel):
    username: str
    content: str


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
    instance_info = get_instance_metadata()
    messages = await chat_app.get_messages()
    return {
        "messages": messages,
        "instance_info": instance_info
    }


@app.post(API_PREFIX + "/messages")
async def create_message(message: Message):
    instance_info = get_instance_metadata()
    message_dict = {
        "username": message.username,
        "content": message.content,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "instance_info": instance_info
    }

    await chat_app.save_message(message_dict)
    await chat_app.broadcast_message(message_dict)
    return {"status": "success", "message": message_dict}


@app.websocket(API_PREFIX + "/ws/{username}")
async def websocket_endpoint(websocket: WebSocket, username: str):
    try:
        await websocket.accept()
        logger.info(f"WebSocket connection accepted for user: {username}")

        instance_info = get_instance_metadata()
        await websocket.send_json({
            "type": "connection_info",
            "instance_info": instance_info,
            "message": f"Connected to instance: {instance_info['instance_id']} in {instance_info['availability_zone']}"
        })

        chat_app.active_connections.append(websocket)
        logger.info(f"Added connection to active_connections for user: {username}")

        try:
            if chat_app.is_redis_available:
                pubsub = chat_app.redis_client.pubsub()
                await pubsub.subscribe('chat_messages')

                while True:
                    try:
                        message = await pubsub.get_message(ignore_subscribe_messages=True)
                        if message and message['type'] == 'message':
                            await websocket.send_json(json.loads(message['data']))
                        await asyncio.sleep(0.1)
                    except Exception as e:
                        logger.error(f"Redis subscription error: {str(e)}")
                        await asyncio.sleep(1)
            else:
                while True:
                    data = await websocket.receive_text()
                    logger.debug(f"Received message from {username}: {data}")
        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected normally for user: {username}")
        except Exception as e:
            logger.error(f"WebSocket error for user {username}: {str(e)}")
    except Exception as e:
        logger.error(f"Failed to establish WebSocket connection for {username}: {str(e)}")
    finally:
        if websocket in chat_app.active_connections:
            chat_app.active_connections.remove(websocket)
        await websocket.close()

def get_instance_metadata():
    try:
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