import chainlit as cl
import websockets
import asyncio
import os

# If you have a .env with WS_SERVER_URL, you can do:
WS_SERVER_URL = os.getenv("WS_SERVER_URL", "ws://localhost:8765")

@cl.on_chat_start
async def on_chat_start():
    """Runs once per session to greet the user."""
    await cl.Message(
        content="Hi! Press the mic icon and speak. Your audio will be sent to our local server, which in turn communicates with Azure. Enjoy!"
    ).send()


@cl.on_audio_start
async def on_audio_start():
    """
    Called when the user clicks on the microphone to start recording.
    We connect to the local WebSocket server and store the connection.
    We also start a background task to listen for server responses.
    """
    # Create a new WebSocket connection and store it in session
    try:
        websocket = await websockets.connect(WS_SERVER_URL)
        cl.user_session.set("ws_connection", websocket)

        # Kick off a background task to listen for messages from the server
        asyncio.create_task(listen_server_messages(websocket))

        return True  # Indicate success
    except Exception as e:
        await cl.ErrorMessage(
            content=f"Failed to connect to local WS server: {e}"
        ).send()
        return False  # Indicate failure -> won't record audio


async def listen_server_messages(websocket):
    """
    Runs in the background while the user is connected/recording.
    Handles text or audio frames from the server and streams them to the Chainlit UI.
    """
    track_id = "my-audio-track"  # or some unique ID

    try:
        async for message in websocket:
            # The server might send text (JSON) or raw audio bytes
            # We’ll assume that if it’s not valid JSON, it’s audio
            try:
                # Attempt to parse JSON
                data = None
                data = await parse_json_or_none(message)
                if data is not None:
                    # We have a JSON structure, e.g. {type: "azure_text", payload: "..."}
                    if data.get("type") == "azure_text":
                        text_chunk = data.get("payload", "")
                        if text_chunk:
                            # Stream partial text to the UI
                            await cl.Message(content=text_chunk).send()
                    else:
                        # Possibly other structured data
                        pass
                else:
                    # If not JSON, treat as audio bytes
                    # Because websockets always handle text vs. binary frames,
                    # we might need a separate approach if the server is truly
                    # sending raw bytes. Let's handle that scenario:
                    if isinstance(message, bytes):
                        # It's raw PCM16
                        await cl.context.emitter.send_audio_chunk(
                            cl.OutputAudioChunk(
                                mimeType="audio/wav",  # or "pcm16" if your server sends raw
                                data=message,
                                track=track_id
                            )
                        )
                    else:
                        # If the server is sending text for some reason:
                        await cl.Message(content=message).send()

            except Exception as e:
                # If an error occurs or it's not JSON
                # You could fallback to raw bytes or logging
                await cl.Message(content=f"Unrecognized message: {message[:100]}").send()
    except websockets.ConnectionClosed:
        pass
    finally:
        # When the loop ends, the server closed connection or user ended
        pass


async def parse_json_or_none(message):
    """
    Attempt to parse a string as JSON. If it's invalid JSON,
    return None. If it's raw bytes, raise an error from decode.
    """
    if isinstance(message, bytes):
        # It's binary, not JSON
        return None
    try:
        data = json.loads(message)
        return data
    except:
        return None


@cl.on_audio_chunk
async def on_audio_chunk(chunk: cl.InputAudioChunk):
    """
    Called for every audio frame from the user's microphone.
    We forward these bytes to the local server.
    """
    websocket = cl.user_session.get("ws_connection")
    if websocket:
        # chunk.data is raw PCM16
        # We can just send it as raw binary
        await websocket.send(chunk.data)


@cl.on_audio_end
async def on_audio_end():
    """
    Called when the user stops recording. Optionally, we can tell
    the server we’re done sending audio for now.
    """
    websocket = cl.user_session.get("ws_connection")
    if websocket:
        # We can send a "DONE" message or no-op, depending on your server logic
        try:
            await websocket.send("END_OF_AUDIO")
        except:
            pass


@cl.on_chat_end
@cl.on_stop
async def on_chat_end():
    """
    Called when the user closes the chat or resets it.
    We close the WebSocket connection if still open.
    """
    websocket = cl.user_session.get("ws_connection")
    if websocket:
        try:
            await websocket.close()
        except:
            pass
        finally:
            cl.user_session.set("ws_connection", None)
