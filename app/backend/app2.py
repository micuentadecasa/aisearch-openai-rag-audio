import asyncio
import websockets
import logging
import json
import os

# Import your RealtimeClient and any relevant tools
from realtime import RealtimeClient
from realtime.tools import tools

logging.basicConfig(level=logging.INFO)

SYSTEM_PROMPT = """Provide empathetic support in a helpful, service-oriented tone.
Ensure any user data is kept private. 
"""

# The main handler for new WebSocket connections
async def openai_bridge_handler(websocket):
    # 1) Create a fresh RealtimeClient
    openai_realtime = RealtimeClient(system_prompt=SYSTEM_PROMPT)

    # 2) (Optional) Add your desired tools
    #    This uses the definitions from your 'tools.py' file
    for tool_def, tool_handler in tools:
        await openai_realtime.add_tool(tool_def, tool_handler)

    # 3) Connect to Azure OpenAI Realtime
    await openai_realtime.connect()

    # 4) Set up callbacks so that we can forward audio or text from Azure -> user
    #    We'll define minimal handlers to send data back through the user's WebSocket.
    async def handle_conversation_updated(event):
        """
        Called when the RealtimeClient processes an update from Azure,
        e.g., partial audio or partial text.
        """
        delta = event.get("delta", {})
            # If delta is None, there's nothing further to process
        if not delta:
            return

        if "text" in delta:
            # Text chunk from Azure
            text_chunk = delta["text"]
            # Send it back to the user as text
            await websocket.send(json.dumps({"type": "azure_text", "payload": text_chunk}))
        if "audio" in delta:
            # Audio chunk from Azure (bytes in int16 PCM)
            audio_chunk = delta["audio"]
            # Send it back to the user as a binary frame
            await websocket.send(audio_chunk)  # or websocket.send(bytes(...)) if needed
        # ... handle function call arguments, transcripts, etc. as needed

    async def handle_item_completed(event):
        """
        Called when a message or tool call is fully completed.
        For now, we just log it.
        """
        item = event.get("item")
        logging.info(f"[Realtime] Item completed: {item}")

    async def handle_error(event):
        logging.error(f"[Realtime] Error event: {event}")

    # 5) Register the event listeners on the RealtimeClient
    openai_realtime.on("conversation.updated", handle_conversation_updated)
    openai_realtime.on("conversation.item.completed", handle_item_completed)
    openai_realtime.on("error", handle_error)

    # 6) Main loop: read incoming frames from the user
    #    For text -> forward as user message
    #    For binary -> treat it as audio
    try:
        while True:
            message = await websocket.recv()
            if isinstance(message, str):
                logging.info(f"[User->Server] Text: {message}")
                # Send the text message to Azure
                # RealtimeClient expects an array of dict objects, e.g., {type: 'input_text', text: 'Hello'}
                await openai_realtime.send_user_message_content([{
                    "type": "input_text",
                    "text": message
                }])
            elif isinstance(message, bytes):
                logging.info(f"[User->Server] Audio bytes: {len(message)} bytes")
                # Send the audio chunk to Azure
                await openai_realtime.append_input_audio(message)

    except websockets.ConnectionClosed:
        logging.info("[User] Disconnected.")
    finally:
        # On user disconnect, gracefully close the Azure Realtime connection
        await openai_realtime.disconnect()

# Main entry point: Start the local WS server
async def main():
    async with websockets.serve(openai_bridge_handler, "0.0.0.0", 8765):
        logging.info("Local WebSocket server on ws://0.0.0.0:8765")
        await asyncio.Future()  # block forever

if __name__ == "__main__":
    asyncio.run(main())
