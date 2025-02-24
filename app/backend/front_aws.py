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
    """Listens for responses from AWS WebSocket and processes audio and transcript."""
    global audio_buffer
    try:
        async for message_bytes in websocket:
            message_str = message_bytes.decode('utf-8', errors='ignore')
            try:
                # Log all messages
                with open("logs_messages_aws.txt", "a") as log_file:
                    log_file.write(f"Received Message (String):\n{message_str}\n\n")

                response = json.loads(message_str)

                # Handle assistant audio chunks
                if "assistant_audio" in response:
                    audio_chunk_b64 = response["assistant_audio"]
                    if audio_chunk_b64: # Check if audio_chunk_b64 is not empty
                        try:
                            audio_bytes = base64.b64decode(audio_chunk_b64)
                            await cl.context.emitter.send_audio_chunk(
                                cl.OutputAudioChunk(
                                    mimeType="audio/wav",  # Adjust if needed
                                    data=audio_bytes,
                                    track="assistant_audio"
                                )
                            )
                            audio_buffer += audio_chunk_b64 # Keep appending to buffer for potential later use (though might not be needed)
                        except base64.binascii.Error as e_b64:
                            print(f"[Base64 Decode Error (assistant_audio)]: {e_b64}")
                            with open("logs_messages_aws.txt", "a") as log_file:
                                log_file.write(f"Base64 Decode Error (assistant_audio): {e_b64}\nMessage: {message_str}\n\n")

                # Handle assistant transcript (final message)
                if "assistant_transcript" in response:
                    transcript = response.get("assistant_transcript") # Use .get to avoid KeyError if absent (though unlikely based on description)
                    if transcript:
                        if audio_buffer:
                            audio_buffer = ""  # Reset buffer after transcript received (if buffering is actually needed)
                        await cl.Message(content=transcript).send()

            except json.JSONDecodeError as e_json:
                print(f"[JSON Decode Error]: {e_json}")
                print(f"Problematic Message (String):\n{message_str}")
                with open("logs_messages_aws.txt", "a") as log_file:
                    log_file.write(f"JSON Decode Error: {e_json}\nMessage (String):\n{message_str}\n\n")
                await cl.ErrorMessage(content="Error processing server message (JSON decode failed). Check logs.").send() # Inform user of JSON error

            except Exception as e_general: # Catch any other unexpected errors in message processing
                print(f"[General Message Processing Error]: {e_general}")
                print(f"Message caused error (String):\n{message_str}")
                with open("logs_messages_aws.txt", "a") as log_file:
                    log_file.write(f"General Message Processing Error: {e_general}\nMessage (String):\n{message_str}\n\n")
                await cl.ErrorMessage(content="Error processing server message. Check logs.").send() # Inform user of general error

    except websockets.ConnectionClosed:
        print("[WebSocket] Connection closed.")
    except Exception as e_connection: # Catch potential errors outside the message loop
        print(f"[WebSocket Listener Error]: {e_connection}")
        with open("logs_messages_aws.txt", "a") as log_file:
            log_file.write(f"WebSocket Listener Error: {e_connection}\n\n")
        await cl.ErrorMessage(content="WebSocket listener encountered an error. Check logs.").send()
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
                "type": "audio",
                "message": encoded_audio  # Sending base64-encoded audio
            }
        }
        json_payload = json.dumps(payload)
        print(f"[WebSocket] Sending audio: {json_payload[:100]}... (truncated)")
        await websocket.send(json_payload)
        # Log the audio chunk to the logs_chunks_audio_sent.txt file
        with open("logs_chunks_audio_sent.txt", "a") as log_file:
            log_file.write(f"{encoded_audio}\n")
        #await websocket.send(chunk.data)
    else:
        print("[WebSocket ERROR] No active WebSocket connection.")


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
