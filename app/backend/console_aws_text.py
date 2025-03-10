# script to test the AWS WebSocket connection from command line and not having to use the Gradio interface

import os
import json
import asyncio
import websockets
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Load WebSocket URL and Auth Token
WS_SERVER_URL = os.getenv("WS_SERVER_URL", "wss://57a3pumjpe.execute-api.eu-west-1.amazonaws.com/default")
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "your_auth_token_here")

async def send_text_message(websocket, message):
    # Prepare the payload
    payload = {
        "action": "metahuman",
        "body": {
            "type": "text",
            ": message
        }
    }
    json_payload = json.dumps(payload)
    print(f"[WebSocket] Sending text message: {json_payload}")
    await websocket.send(json_payload)

async def receive_messages(websocket):
    # Listen for responses
    async for message in websocket:
        truncated_message = message[-200:]  # Keep the last 100 characters
        print(f"[WebSocket] Received message: {truncated_message}... (truncated)")
        with open("./app/backend/logs_text_received_console.txt", "a") as log_file:
            log_file.write(f"{truncated_message}... (truncated)\n")

async def main():
    websocket_url = f"{WS_SERVER_URL}?authorizationToken={AUTH_TOKEN}"
    print(f"[WebSocket] Connecting to: {websocket_url}")

    try:
        async with websockets.connect(websocket_url) as websocket:
            print(f"[WebSocket] Connected to {WS_SERVER_URL}")

            # Create a task to receive messages
            receive_task = asyncio.create_task(receive_messages(websocket))

            # Send a text message
            await send_text_message(websocket, "Hello, this is a test message.")
            await send_text_message(websocket, "give me my orders.")


            # Wait for the receive task to complete
            await receive_task

    except Exception as e:
        print(f"[WebSocket ERROR] {e}")

if __name__ == "__main__":
    asyncio.run(main())