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
    """Listens for responses from AWS WebSocket, buffers JSON fragments, and processes messages."""
    global audio_buffer
    json_buffer = ""  # Initialize JSON buffer for accumulating fragments
    audio_buffer = ""  # Initialize audio buffer for accumulating audio chunks
    is_collecting = False  # Flag to track if we're collecting fragments
    
    try:
        async for message in websocket:
            if isinstance(message, bytes):
                message_str = message.decode('utf-8', errors='ignore')
            elif isinstance(message, str):
                message_str = message
            else:
                print(f"[WebSocket] Received unexpected message type: {type(message)}")
                with open("logs_messages_aws.txt", "a") as log_file:
                    log_file.write(f"Unexpected message type: {type(message)}\nMessage: {message}\n\n")
                continue

            # Append current message to buffer
            json_buffer += message_str
            
            # Check if this is the start of audio collection
            if not is_collecting and '"assistant_audio":' in message_str:
                is_collecting = True
                print("[WebSocket] Started collecting audio fragments")
            
            # Check if we have a complete message with transcript
            if '"assistant_transcript"' in message_str:
                is_collecting = False
                print("[WebSocket] Found transcript, processing complete message")
                #print(f"[WebSocket] Complete message: {json_buffer}")

                try:
                    # Parse the complete JSON object
                    response = json.loads(json_buffer)
                    
                    # Log the complete message
                    with open("logs_messages_aws.txt", "a") as log_file:
                        log_file.write(f"Received complete JSON Object:\n{json_buffer}\n\n")
                   
                    # Handle the complete audio
                    if "assistant_audio" in response:
                        print("starting to decode audio")
                        audio_chunk_b64 = response["assistant_audio"]
                        if audio_chunk_b64:
                            try:
                                print("starting to play audio")
                                # Decode and play the full audio
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
                    
                    # Handle the transcript
                    if "assistant_transcript" in response:
                        transcript = response.get("assistant_transcript")
                        if transcript:
                            await cl.Message(content=transcript).send()
                    
                    # Clear the buffers after successful processing
                    json_buffer = ""
                    audio_buffer = ""
                    
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
            
            # If we're not collecting and this isn't part of an audio message, 
            # try to process it as a standalone message
            elif not is_collecting:
                try:
                    # Try to parse as a standalone message
                    response = json.loads(json_buffer)
                    
                    # Log the message
                    with open("logs_messages_aws.txt", "a") as log_file:
                        log_file.write(f"Received standalone JSON Object:\n{json_buffer}\n\n")
                    
                    # Process any non-audio/transcript messages here if needed
                    # ...
                    
                    # Clear the buffer
                    json_buffer = ""
                    
                except json.JSONDecodeError:
                    # Not a complete JSON, might be the start of something else
                    # Just keep buffering
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
