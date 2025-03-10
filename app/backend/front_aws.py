import base64
import json
import os
import websockets
import asyncio
import chainlit as cl
import time
from datetime import datetime

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
        print("starting")
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
    """Listens for responses from AWS WebSocket, buffers multi-chunk messages, and processes them."""
    json_buffer = ""  # Buffer for accumulating incomplete JSON fragments.
    audio_chunks = []  # List to store base64-encoded audio chunks.

    try:
        async for message in websocket:
            # Convert message to string.
            if isinstance(message, bytes):
                message_str = message.decode('utf-8', errors='ignore')
            elif isinstance(message, str):
                message_str = message
            else:
                print(f"[WebSocket] Received unexpected message type: {type(message)}")
                continue

            # Attempt to parse the JSON.
            try:
                response = json.loads(message_str)
                # print the response truncating the audio
                # add time to the logs
                print(f"[listen_server_messages] Received at {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}: {json.dumps(response, indent=2)[:100]}... (audio truncated)")
            except json.JSONDecodeError:
                json_buffer += message_str
                try:
                    response = json.loads(json_buffer)
                    json_buffer = ""
                except json.JSONDecodeError:
                    continue  # Wait for more fragments.

            # Check for multi-chunk messages.
            if "chunk_index" in response and "total_chunks" in response:
                # Append current audio chunk.
                audio_chunk_b64 = response.get("assistant_audio", "")
                if audio_chunk_b64:
                    audio_chunks.append(audio_chunk_b64)

                # If this is not the final chunk, wait for more.
                if response["chunk_index"] < response["total_chunks"]:
                    print(f"[listen_server_messages] Received chunk {response['chunk_index']} of {response['total_chunks']}.")
                    continue
                else:
                    # Final chunk received: combine all chunks.
                    try:
                        print(f"[listen_server_messages] Received final chunk {response['chunk_index']} of {response['total_chunks']}.")
                        combined_audio = b"".join(
                            base64.b64decode(chunk) for chunk in audio_chunks
                        )
                        print(f"[listen_server_messages] playing combined audio of length {len(combined_audio)} bytes.")
                        await cl.context.emitter.send_audio_chunk(
                            cl.OutputAudioChunk(
                                mimeType="audio/wav",
                                data=combined_audio,
                                track="assistant_audio"
                            )
                        )
                    except Exception as e:
                        print(f"[WebSocket] Error processing combined audio: {e}")

                    # Process transcript if available.
                    transcript = response.get("assistant_transcript", "")
                    if transcript:
                        await cl.Message(content=transcript).send()

                    # Clear the audio chunks for the next multi-chunk message.
                    audio_chunks = []

            else:
                # Process single (non-chunked) message as before.
                if "assistant_audio" in response:
                    print(f"[listen_server_messages] Received audio single chunk.")
                    audio_chunk_b64 = response["assistant_audio"]
                    if audio_chunk_b64:
                        try:
                            audio_bytes = base64.b64decode(audio_chunk_b64)
                            await cl.context.emitter.send_audio_chunk(
                                cl.OutputAudioChunk(
                                    mimeType="audio/wav",
                                    data=audio_bytes,
                                    track="assistant_audio"
                                )
                            )
                        except Exception as e:
                            print(f"[Base64 Decode Error]: {e}")
                if "assistant_transcript" in response:
                    transcript = response.get("assistant_transcript")
                    if transcript:
                        await cl.Message(content=transcript).send()

    except websockets.ConnectionClosed:
        print("[WebSocket] Connection closed.")
    except Exception as e:
        print(f"[WebSocket Listener Error]: {e}")
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
                "type": "text",
                "message": message.content,
                "token": "234kh234hjh34"
            }
        }
        json_payload = json.dumps(payload)
        print(f": {json_payload}")
        # put the current time in the logs
        print(f"[WebSocket] Sending message: {message.content} at {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}")
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
    """Sends audio as base64-encoded payload to AWS WebSocket, matching Lambda expectations."""

    # if len of audio is 8192 bytes then return, because it is a silence
    #if len(chunk.data) == 8192:
    #    print("[WebSocket] Audio chunk is silence, skipping.")
    #    return

    websocket = cl.user_session.get("ws_connection")

    if not websocket:
        print("[WebSocket ERROR] No active WebSocket connection.")
        return

    # Ensure chunk is not empty
    bytes_length = len(chunk.data)
    if bytes_length == 0:
        return

    print(f"[WebSocket] Audio bytes: {bytes_length} bytes")

    try:
        # Convert audio bytes to Base64 (mimicking array_buffer_to_base64)
        encoded_audio = base64.b64encode(chunk.data).decode("utf-8")

        # Send message in correct format for Lambda function
        payload = {
            "action": "metahuman",
            "body": {
                "type": "audio",
                "message": encoded_audio  # Base64-encoded audio
                ,"token": "234kh234hjh34" }
        }

        json_payload = json.dumps(payload)
        print(f"[WebSocket] Sending audio: {json_payload}")
        await websocket.send(json_payload)

        # Store locally for debugging (optional)
        cl.user_session.set("audio_buffer", cl.user_session.get("audio_buffer", []) + [chunk.data])

        # Log the audio chunk for debugging
        with open("logs_chunks_audio_sent.txt", "a") as log_file:
            log_file.write(f"{encoded_audio}\n")

    except Exception as e:
        print(f"[WebSocket] Error sending audio chunk: {e}")



@cl.on_audio_end
async def on_audio_end():
    """Handles the end of an audio stream and notifies the WebSocket."""
    websocket = cl.user_session.get("ws_connection")
    if websocket:
        print("[WebSocket] Audio transmission ended.")
        await websocket.send(json.dumps({"action": "metahuman", "body": {"type":"text","message": "END_OF_AUDIO"}}))


@cl.on_chat_end
@cl.on_stop
async def on_chat_end():
    """Closes WebSocket connection when the chat session ends."""
    websocket = cl.user_session.get("ws_connection")
    if websocket:
        print("[WebSocket] Closing connection.")
        await websocket.close()
        cl.user_session.set("ws_connection", None)
