import base64
import json
import os
import websockets
import asyncio
import chainlit as cl

# Load WebSocket URL and Auth Token
WS_SERVER_URL = os.getenv("WS_SERVER_URL", "wss://57a3pumjpe.execute-api.eu-west-1.amazonaws.com/default")
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "your_auth_token_here")

# Store global WebSocket connection
websocket = None

@cl.on_chat_start
async def on_chat_start():
    """Start WebSocket connection on chat start."""
    global websocket
    try:
        websocket_url = f"{WS_SERVER_URL}?authorizationToken={AUTH_TOKEN}"
        print(f"[WebSocket] Connecting to: {websocket_url}")
        
        websocket = await websockets.connect(websocket_url)
        cl.user_session.set("ws_connection", websocket)

        print(f"[WebSocket] Connected to {WS_SERVER_URL}")

        # Start listening for messages
        asyncio.create_task(listen_server_messages(websocket))

    except Exception as e:
        print(f"[WebSocket ERROR] Failed to connect: {e}")
        await cl.ErrorMessage(content=f"WebSocket connection failed: {e}").send()


async def listen_server_messages(websocket):
    """Listens for responses from AWS WebSocket and logs them."""
    try:
        async for message in websocket:
            try:
                with open("logs_messages_aws.txt", "a") as log_file:
                    log_file.write(f"{message}\n\n")
                response = json.loads(message)
                

                # Handle assistant responses
                if "message" in response:
                    await cl.Message(content=response["message"]).send()
                else:
                    print(f"[WebSocket] Unknown response format: {response}")

            except json.JSONDecodeError:
                print(f"[WebSocket] Non-JSON message received: {message}")

    except websockets.ConnectionClosed:
        print("[WebSocket] Connection closed.")
    finally:
        print("[WebSocket] Listener stopped.")


@cl.on_message
async def on_message(message: cl.Message):
    """Handles text messages and sends them to the WebSocket in the correct format."""
    websocket = cl.user_session.get("ws_connection")
    
    if websocket:
        payload = {
            "action": "metahuman",
            "body": {
                "message": message.content
            }
        }
        json_payload = json.dumps(payload)
        print(f"[WebSocket] Sending text: {json_payload}")
        await websocket.send(json_payload)
    else:
        print("[WebSocket ERROR] No active WebSocket connection.")


@cl.on_audio_start
async def on_audio_start():
    """Starts audio session, logs, and ensures WebSocket is ready."""
    websocket = cl.user_session.get("ws_connection")
    if websocket:
        print("[WebSocket] Ready for audio streaming.")
        return True
    else:
        print("[WebSocket ERROR] WebSocket is not connected.")
        return False


@cl.on_audio_chunk
async def on_audio_chunk(chunk: cl.InputAudioChunk):
    """Sends audio as base64 encoded payload to AWS WebSocket."""
    websocket = cl.user_session.get("ws_connection")
    
    if websocket:
        encoded_audio = base64.b64encode(chunk.data).decode("utf-8")
        payload = {
            "action": "metahuman",
            "body": {
                "message": encoded_audio  # Sending base64-encoded audio
            }
        }
        json_payload = json.dumps(payload)
        print(f"[WebSocket] Sending audio: {json_payload[:100]}... (truncated)")
        await websocket.send(json_payload)
        # old code, We can just send it as raw binary
        #await websocket.send(chunk.data)
    else:
        print("[WebSocket ERROR] No active WebSocket connection.")


@cl.on_audio_end
async def on_audio_end():
    """Handles the end of an audio stream and notifies the WebSocket."""
    websocket = cl.user_session.get("ws_connection")
    if websocket:
        print("[WebSocket] Audio transmission ended.")
        await websocket.send(json.dumps({"action": "metahuman", "body": {"message": "END_OF_AUDIO"}}))


@cl.on_chat_end
@cl.on_stop
async def on_chat_end():
    """Closes WebSocket connection when the chat session ends."""
    websocket = cl.user_session.get("ws_connection")
    if websocket:
        print("[WebSocket] Closing connection.")
        await websocket.close()
        cl.user_session.set("ws_connection", None)
