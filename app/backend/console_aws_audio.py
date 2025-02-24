import os
import json
import base64
import asyncio
import websockets
from dotenv import load_dotenv
import time

# Load environment variables from .env file
load_dotenv()

# Load WebSocket URL and Auth Token
WS_SERVER_URL = os.getenv("WS_SERVER_URL", "wss://57a3pumjpe.execute-api.eu-west-1.amazonaws.com/default")
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "your_auth_token_here")

# Define the maximum chunk size
MAX_CHUNK_SIZE = 32000  # 32 KB

async def send_file_content(websocket, file_name):
    # Read the base64 encoded audio file
    audio_file_path = os.path.join("./app/backend/audios", file_name)
    with open(audio_file_path, "r") as file:
        encoded_audio = file.read().strip()

    # Split the encoded audio into chunks
    for i in range(0, len(encoded_audio), MAX_CHUNK_SIZE):
        chunk = encoded_audio[i:i + MAX_CHUNK_SIZE]

        # Prepare the payload
        payload = {
            "action": "metahuman",
            "body": {
                "type": "audio",
                "message": chunk
            }
        }
        json_payload = json.dumps(payload)
        print(f"[WebSocket] Sending audio chunk: {json_payload[:100]}... (truncated)")
        await websocket.send(json_payload)

async def receive_messages(websocket):
    # Listen for responses
    async for message in websocket:
        truncated_message = message[-100:]  # Keep the last 100 characters
        print(f"[WebSocket] Received message: {truncated_message}... (truncated)")
        with open("./app/backend/logs_chunks_audio_received_console.txt", "a") as log_file:
            log_file.write(f"{truncated_message}... (truncated)\n")

async def main():
    websocket_url = f"{WS_SERVER_URL}?authorizationToken={AUTH_TOKEN}"
    print(f"[WebSocket] Connecting to: {websocket_url}")

    try:
        async with websockets.connect(websocket_url) as websocket:
            print(f"[WebSocket] Connected to {WS_SERVER_URL}")

            # Create a task to receive messages
            receive_task = asyncio.create_task(receive_messages(websocket))

            # Send content of the first file
            #await send_file_content(websocket, "record_myOrders_b64.txt")

            # Wait for 1 second
            await asyncio.sleep(1)

            # Send content of the second file
            await send_file_content(websocket, "record_clientId_b64.txt")

            # Wait for the receive task to complete
            await receive_task

    except Exception as e:
        print(f"[WebSocket ERROR] {e}")

if __name__ == "__main__":
    asyncio.run(main())