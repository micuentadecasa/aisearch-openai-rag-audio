import base64
import json
import os
import websockets
import asyncio
import chainlit as cl
from collections import deque

# Load WebSocket URL and Auth Token
WS_SERVER_URL = os.getenv("WS_SERVER_URL", "wss://57a3pumjpe.execute-api.eu-west-1.amazonaws.com/default")
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "your_auth_token_here")

# Queue to store audio chunks
audio_chunk_queue = deque()

@cl.on_chat_start
async def on_chat_start():
    """Start WebSocket connection on chat start and set up receiving audio."""
    try:
        # Generate a unique session ID for tracking this conversation
        session_id = f"session_{int(asyncio.get_event_loop().time() * 1000)}"
        cl.user_session.set("session_id", session_id)
        print(f"[WebSocket] Generated session ID: {session_id}")

        websocket_url = f"{WS_SERVER_URL}?authorizationToken={AUTH_TOKEN}"
        print(f"[WebSocket] Connecting to: {websocket_url}")
        
        websocket = await websockets.connect(websocket_url)
        cl.user_session.set("ws_connection", websocket)
        # Store audio receiving state
        cl.user_session.set("audio_receiving_enabled", True)

        print(f"[WebSocket] Connected to {WS_SERVER_URL}")
        
        # Tell the server we want to receive audio
        init_payload = {
            "action": "metahuman",
            "body": {
                "type": "control",
                "message": "ENABLE_AUDIO_RECEIVING"
            }
        }
        await websocket.send(json.dumps(init_payload))

        # Start listening for messages as a separate task
        listener_task = asyncio.create_task(listen_server_messages(websocket))
        cl.user_session.set("listener_task", listener_task)

    except Exception as e:
        print(f"[WebSocket ERROR] Failed to connect: {e}")
        await cl.ErrorMessage(content=f"WebSocket connection failed: {e}").send()

async def listen_server_messages(websocket):
    """
    Listens for responses from AWS WebSocket, buffers JSON fragments, and processes messages.
    Handles both audio and transcript messages.
    """
    json_buffer = ""  # Buffer for accumulating JSON fragments
    is_collecting = False  # Flag for audio fragment collection
    
    try:
        async for message in websocket:
            # Skip processing if audio receiving is disabled
            if not cl.user_session.get("audio_receiving_enabled", True):
                continue
                
            if isinstance(message, bytes):
                message_str = message.decode('utf-8', errors='ignore')
            elif isinstance(message, str):
                message_str = message
            else:
                print(f"[WebSocket] Received unexpected message type: {type(message)}")
                with open("logs_messages_aws.txt", "a") as log_file:
                    log_file.write(f"Unexpected message type: {type(message)}\nMessage: {message}\n\n")
                continue

            # Append incoming message to the buffer
            json_buffer += message_str
            
            # Check if this message contains audio start indicator
            if not is_collecting and '"assistant_audio":' in message_str:
                is_collecting = True
                print("[WebSocket] Started collecting audio fragments")
            
            # Check if transcript is present to mark the end of the audio collection
            if '"assistant_transcript"' in message_str:
                is_collecting = False
                print("[WebSocket] Found transcript, processing complete message")

                try:
                    # Parse the complete JSON object
                    response = json.loads(json_buffer)
                    
                    # Log the complete message
                    with open("logs_messages_aws.txt", "a") as log_file:
                        log_file.write(f"Received complete JSON Object:\n{json_buffer}\n\n")
                   
                    # Handle audio playback if present
                    if "assistant_audio" in response:
                        print("starting to decode audio")
                        audio_chunk_b64 = response["assistant_audio"]
                        if audio_chunk_b64:
                            try:
                                print("starting to play audio")
                                audio_bytes = base64.b64decode(audio_chunk_b64)
                                await cl.context.emitter.send_audio_chunk(
                                    cl.OutputAudioChunk(
                                        mimeType="audio/wav",
                                        data=audio_bytes,
                                        track="assistant_audio"
                                    )
                                )
                                print("finished playing audio")
                            except base64.binascii.Error as e_b64:
                                print(f"[Base64 Decode Error]: {e_b64}")
                                with open("logs_messages_aws.txt", "a") as log_file:
                                    log_file.write(f"Base64 Decode Error: {e_b64}\nMessage: {message_str}\n\n")
                    
                    # Handle transcript message if present
                    if "assistant_transcript" in response:
                        transcript = response.get("assistant_transcript")
                        if transcript:
                            await cl.Message(content=transcript).send()
                    
                    # Clear the JSON buffer after processing
                    json_buffer = ""
                    
                except json.JSONDecodeError as e_json:
                    print(f"[WebSocket] Error parsing complete message: {e_json}")
                    with open("logs_messages_aws.txt", "a") as log_file:
                        log_file.write(f"Error parsing complete message: {e_json}\nBuffer: {json_buffer}\n\n")
                    await cl.ErrorMessage(content="Error processing server message. Check logs.").send()
                    json_buffer = ""
                    
                except Exception as e_general:
                    print(f"[General Processing Error]: {e_general}")
                    with open("logs_messages_aws.txt", "a") as log_file:
                        log_file.write(f"General Processing Error: {e_general}\nBuffer: {json_buffer}\n\n")
                    await cl.ErrorMessage(content="Error processing server message. Check logs.").send()
                    json_buffer = ""
            
            # For standalone messages that aren't part of audio collection
            elif not is_collecting:
                try:
                    response = json.loads(json_buffer)
                    with open("logs_messages_aws.txt", "a") as log_file:
                        log_file.write(f"Received standalone JSON Object:\n{json_buffer}\n\n")
                    json_buffer = ""
                except json.JSONDecodeError:
                    # Incomplete JSON; continue buffering
                    pass
    
    except websockets.ConnectionClosed:
        print("[WebSocket] Connection closed.")
    except Exception as e_connection:
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
                "message": message.content,
                "session_id": cl.user_session.get("session_id", "default_session"),
                "timestamp": str(int(asyncio.get_event_loop().time() * 1000))
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
        audio_session_id = f"audio_{int(asyncio.get_event_loop().time() * 1000)}"
        cl.user_session.set("current_audio_session", audio_session_id)
        print(f"[WebSocket] Ready for audio streaming. Session ID: {audio_session_id}")
        
        start_payload = {
            "action": "metahuman",
            "body": {
                "type": "control",
                "message": "START_AUDIO_STREAM",
                "audio_session_id": audio_session_id,
                "timestamp": str(int(asyncio.get_event_loop().time() * 1000))
            }
        }
        await websocket.send(json.dumps(start_payload))
        return True
    else:
        print("[WebSocket ERROR] WebSocket is not connected.")
        return False

@cl.on_audio_chunk
async def on_audio_chunk(chunk: cl.InputAudioChunk):
    """Processes audio chunks and sends them efficiently."""
    websocket = cl.user_session.get("ws_connection")
    
    if websocket:
        # Add to queue
        audio_chunk_queue.append(chunk)
        
        # Process the queue in a non-blocking way
        asyncio.create_task(process_audio_queue(websocket))
    else:
        print("[WebSocket ERROR] No active WebSocket connection.")

async def process_audio_queue(websocket):
    """Process audio queue without blocking the main thread."""
    global audio_chunk_queue
    
    # Only process if we have enough chunks and no other process is running
    processing_key = "is_processing_audio_queue"
    if len(audio_chunk_queue) >= 5 and not cl.user_session.get(processing_key, False):
        try:
            cl.user_session.set(processing_key, True)
            await send_audio_batch(websocket)
        finally:
            cl.user_session.set(processing_key, False)

async def send_audio_batch(websocket):
    """Sends a batch of audio chunks to the WebSocket, ensuring the JSON payload is below the size limit."""
    global audio_chunk_queue
    audio_session_id = cl.user_session.get("current_audio_session", "unknown_session")
    
    max_frame_size = 32768  # Maximum frame length in bytes
    safety_margin = 1024     # Safety margin for JSON overhead
    max_payload_size = max_frame_size - safety_margin
    
    batch_payload = {
        "action": "metahuman",
        "body": {
            "type": "audio",
            "audio_session_id": audio_session_id,
            "chunks": [],
            "timestamp": str(int(asyncio.get_event_loop().time() * 1000))
        }
    }
    
    # Add chunks until adding another would exceed the payload size limit
    while audio_chunk_queue:
        next_chunk = audio_chunk_queue[0]  # Peek at the next chunk
        encoded_audio = base64.b64encode(next_chunk.data).decode("utf-8")
        temp_chunks = batch_payload["body"]["chunks"] + [{"message": encoded_audio}]
        temp_payload = {
            "action": "metahuman",
            "body": {
                "type": "audio",
                "audio_session_id": audio_session_id,
                "message": temp_chunks,
                "timestamp": batch_payload["body"]["timestamp"]
            }
        }
        temp_json = json.dumps(temp_payload)
        if len(temp_json.encode('utf-8')) < max_payload_size:
            # It is safe to add this chunk
            audio_chunk_queue.popleft()
            batch_payload["body"]["chunks"].append({"message": encoded_audio})
        else:
            # Adding this chunk would exceed the limit, so break out
            break
    
    if batch_payload["body"]["chunks"]:
        json_payload = json.dumps(batch_payload)
        print(f"[WebSocket] Sending audio batch: {json_payload[:100]}... (truncated)")
        await websocket.send(json_payload)
        
        # Log the audio batch details
        with open("logs_chunks_audio_sent.txt", "a") as log_file:
            log_file.write(f"Session: {audio_session_id}, Chunks: {len(batch_payload['body']['chunks'])}, Timestamp: {batch_payload['body']['timestamp']}\n")

@cl.on_audio_end
async def on_audio_end():
    """Handles the end of an audio stream and notifies the WebSocket."""
    websocket = cl.user_session.get("ws_connection")
    if websocket:
        audio_session_id = cl.user_session.get("current_audio_session", "unknown_session")
        print(f"[WebSocket] Audio transmission ended for session {audio_session_id}.")
        
        # Send any remaining chunks in the queue
        if audio_chunk_queue:
            await send_audio_batch(websocket)
        
        end_payload = {
            "action": "metahuman",
            "body": {
                "type": "control",
                "message": "END_OF_AUDIO",
                "audio_session_id": audio_session_id,
                "timestamp": str(int(asyncio.get_event_loop().time() * 1000))
            }
        }
        await websocket.send(json.dumps(end_payload))
        # Clear the current audio session
        cl.user_session.set("current_audio_session", None)

@cl.on_chat_end
@cl.on_stop
async def on_chat_end():
    """Closes WebSocket connection when the chat session ends or the user stops interaction."""
    websocket = cl.user_session.get("ws_connection")
    listener_task = cl.user_session.get("listener_task")
    
    if listener_task and not listener_task.done():
        listener_task.cancel()
        try:
            await listener_task
        except asyncio.CancelledError:
            pass
    
    if websocket:
        print("[WebSocket] Closing connection.")
        try:
            await websocket.send(json.dumps({
                "action": "metahuman", 
                "body": {
                    "type": "control",
                    "message": "CLOSE_CONNECTION"
                }
            }))
            await websocket.close()
        except Exception as e:
            print(f"[WebSocket] Error during close: {e}")
        cl.user_session.set("ws_connection", None)