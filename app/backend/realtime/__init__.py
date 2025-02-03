import os
import asyncio
import json
import inspect
import numpy as np
import websockets
import logging
import base64
import traceback
from datetime import datetime
from collections import defaultdict

#######################################################################
# Utility Functions
#######################################################################

def float_to_16bit_pcm(float32_array):
    """
    Converts a numpy array of float32 amplitude data to a numpy array in int16 format.
    """
    int16_array = np.clip(float32_array, -1, 1) * 32767
    return int16_array.astype(np.int16)

def base64_to_array_buffer(base64_string):
    """
    Converts a base64 string to a numpy array buffer (dtype=uint8 by default).
    """
    binary_data = base64.b64decode(base64_string)
    return np.frombuffer(binary_data, dtype=np.uint8)

def array_buffer_to_base64(array_buffer):
    """
    Converts a numpy array buffer or int16 array buffer to a base64 string.
    """
    if isinstance(array_buffer, bytes) or isinstance(array_buffer, bytearray):
        binary_data = array_buffer
    elif array_buffer.dtype == np.float32:
        # Convert float32 array to int16 first
        array_buffer = float_to_16bit_pcm(array_buffer)
        binary_data = array_buffer.tobytes()
    else:
        binary_data = array_buffer.tobytes()

    return base64.b64encode(binary_data).decode("utf-8")

#######################################################################
# Base Event Handler
#######################################################################

class RealtimeEventHandler:
    """
    Simple event handling with asynchronous callbacks. 
    Allows registering multiple handlers for named events.
    """
    def __init__(self):
        self.event_handlers = defaultdict(list)

    def on(self, event_name, handler):
        """ Register a handler for the named event. """
        self.event_handlers[event_name].append(handler)

    def clear_event_handlers(self):
        """ Remove all registered event handlers. """
        self.event_handlers = defaultdict(list)

    def dispatch(self, event_name, event):
        """ Invoke all handlers for event_name, passing 'event' dict to them. """
        for handler in self.event_handlers[event_name]:
            if inspect.iscoroutinefunction(handler):
                asyncio.create_task(handler(event))
            else:
                handler(event)

    async def wait_for_next(self, event_name):
        """ Suspend until the next time 'event_name' is dispatched. """
        future = asyncio.Future()

        def handler(event):
            if not future.done():
                future.set_result(event)

        self.on(event_name, handler)
        return await future

#######################################################################
# RealtimeAPI
#######################################################################

class RealtimeAPI(RealtimeEventHandler):
    """
    Manages direct WebSocket connection to Azure’s Realtime endpoint. 
    Sends/receives JSON messages. 
    """
    def __init__(self):
        super().__init__()
        self.url = os.environ["AZURE_OPENAI_ENDPOINT"]  # e.g. "https://your-aoai-resource.openai.azure.com"
        self.api_key = os.environ["AZURE_OPENAI_API_KEY"]
        self.api_version = "2024-10-01-preview"
        # The deployment name of your GPT-4o Realtime model
        self.azure_deployment = os.environ["AZURE_OPENAI_DEPLOYMENT"]

        self.ws = None
        self.logger = logging.getLogger(__name__)

    def is_connected(self):
        return self.ws is not None

    def log(self, *args):
        # Helper for logging
        self.logger.debug(f"[Websocket/{datetime.utcnow().isoformat()}] {' '.join(str(a) for a in args)}")

    async def connect(self):
        """
        Establish the WebSocket connection to Azure Realtime API.
        """
        if self.is_connected():
            raise Exception("Already connected")

        # Construct the full WebSocket URL
        ws_url = (
            f"{self.url}/openai/realtime"
            f"?api-version={self.api_version}"
            f"&deployment={self.azure_deployment}"
            f"&api-key={self.api_key}"
        )

        # Connect
        self.ws = await websockets.connect(ws_url)
        self.log(f"Connected to {ws_url}")
        asyncio.create_task(self._receive_messages())

    async def _receive_messages(self):
        """
        Continuously read messages from Azure, parse JSON, and dispatch events.
        """
        async for message in self.ws:
            event = json.loads(message)
            if event["type"] == "error":
                self.logger.error("[RealtimeAPI] ERROR: %s", message)
            self.log("received:", event)
            self.dispatch(f"server.{event['type']}", event)
            self.dispatch("server.*", event)

    async def send(self, event_name, data=None):
        """
        Send an event to Azure Realtime API as a JSON message.
        """
        if not self.is_connected():
            raise Exception("RealtimeAPI is not connected")

        data = data or {}
        if not isinstance(data, dict):
            raise Exception("Data must be a dictionary")

        event = {
            "event_id": self._generate_id("evt_"),
            "type": event_name,
            **data
        }
        self.dispatch(f"client.{event_name}", event)
        self.dispatch("client.*", event)
        self.log("sent:", event)
        await self.ws.send(json.dumps(event))

    def _generate_id(self, prefix):
        return f"{prefix}{int(datetime.utcnow().timestamp() * 1000)}"

    async def disconnect(self):
        """
        Close the WebSocket connection.
        """
        if self.ws:
            await self.ws.close()
            self.ws = None
            self.log(f"Disconnected from {self.url}")

#######################################################################
# RealtimeConversation
#######################################################################

class RealtimeConversation:
    """
    Manages conversation items received from Azure Realtime. 
    This includes messages, partial transcripts, audio segments, and function calls.
    """
    # Default sample rate for audio (e.g., 16K)
    default_frequency = 16000  

    EventProcessors = {
        "conversation.item.created": lambda self, e: self._process_item_created(e),
        "conversation.item.truncated": lambda self, e: self._process_item_truncated(e),
        "conversation.item.deleted": lambda self, e: self._process_item_deleted(e),
        "conversation.item.input_audio_transcription.completed": lambda self, e: self._process_input_audio_transcription_completed(e),
        "input_audio_buffer.speech_started": lambda self, e: self._process_speech_started(e),
        "input_audio_buffer.speech_stopped": lambda self, e, b: self._process_speech_stopped(e, b),
        "response.created": lambda self, e: self._process_response_created(e),
        "response.output_item.added": lambda self, e: self._process_output_item_added(e),
        "response.output_item.done": lambda self, e: self._process_output_item_done(e),
        "response.content_part.added": lambda self, e: self._process_content_part_added(e),
        "response.audio_transcript.delta": lambda self, e: self._process_audio_transcript_delta(e),
        "response.audio.delta": lambda self, e: self._process_audio_delta(e),
        "response.text.delta": lambda self, e: self._process_text_delta(e),
        "response.function_call_arguments.delta": lambda self, e: self._process_function_call_arguments_delta(e),
    }

    def __init__(self):
        self.clear()

    def clear(self):
        self.item_lookup = {}
        self.items = []
        self.response_lookup = {}
        self.responses = []
        self.queued_speech_items = {}
        self.queued_transcript_items = {}
        self.queued_input_audio = None

    def queue_input_audio(self, input_audio):
        self.queued_input_audio = input_audio

    def process_event(self, event, *args):
        processor = self.EventProcessors.get(event["type"])
        if not processor:
            raise Exception(f"Missing conversation event processor for {event['type']}")
        return processor(self, event, *args)

    def get_item(self, item_id):
        return self.item_lookup.get(item_id)

    def get_items(self):
        return self.items[:]

    # ----------------------------------------------
    # Event Processing
    # ----------------------------------------------

    def _process_item_created(self, event):
        item = event["item"]
        new_item = item.copy()
        if new_item["id"] not in self.item_lookup:
            self.item_lookup[new_item["id"]] = new_item
            self.items.append(new_item)

        new_item["formatted"] = {"audio": [], "text": "", "transcript": ""}

        # If partial speech was queued for this item
        if new_item["id"] in self.queued_speech_items:
            new_item["formatted"]["audio"] = self.queued_speech_items[new_item["id"]]["audio"]
            del self.queued_speech_items[new_item["id"]]

        # If item has textual content
        if "content" in new_item:
            text_content = [c for c in new_item["content"] if c["type"] in ["text", "input_text"]]
            for content in text_content:
                new_item["formatted"]["text"] += content["text"]

        # If a transcript was queued
        if new_item["id"] in self.queued_transcript_items:
            new_item["formatted"]["transcript"] = self.queued_transcript_items[new_item["id"]]["transcript"]
            del self.queued_transcript_items[new_item["id"]]

        # Set initial status
        if new_item["type"] == "message":
            if new_item["role"] == "user":
                new_item["status"] = "completed"
                if self.queued_input_audio:
                    new_item["formatted"]["audio"] = self.queued_input_audio
                    self.queued_input_audio = None
            else:
                new_item["status"] = "in_progress"
        elif new_item["type"] == "function_call":
            new_item["formatted"]["tool"] = {
                "type": "function",
                "name": new_item["name"],
                "call_id": new_item["call_id"],
                "arguments": ""
            }
            new_item["status"] = "in_progress"
        elif new_item["type"] == "function_call_output":
            new_item["status"] = "completed"
            new_item["formatted"]["output"] = new_item["output"]

        return new_item, None

    def _process_item_truncated(self, event):
        item_id = event["item_id"]
        audio_end_ms = event["audio_end_ms"]
        item = self.item_lookup.get(item_id)
        if not item:
            raise Exception(f"item.truncated: Item {item_id} not found")

        end_index = (audio_end_ms * self.default_frequency) // 1000
        item["formatted"]["transcript"] = ""
        item["formatted"]["audio"] = item["formatted"]["audio"][:end_index]
        return item, None

    def _process_item_deleted(self, event):
        item_id = event["item_id"]
        item = self.item_lookup.get(item_id)
        if not item:
            raise Exception(f"item.deleted: Item {item_id} not found")

        del self.item_lookup[item["id"]]
        self.items.remove(item)
        return item, None

    def _process_input_audio_transcription_completed(self, event):
        item_id = event["item_id"]
        content_index = event["content_index"]
        transcript = event["transcript"] or ""
        item = self.item_lookup.get(item_id)
        if not item:
            self.queued_transcript_items[item_id] = {"transcript": transcript}
            return None, None

        item["content"][content_index]["transcript"] = transcript
        item["formatted"]["transcript"] = transcript
        return item, {"transcript": transcript}

    def _process_speech_started(self, event):
        item_id = event["item_id"]
        audio_start_ms = event["audio_start_ms"]
        self.queued_speech_items[item_id] = {"audio_start_ms": audio_start_ms}
        return None, None

    def _process_speech_stopped(self, event, input_audio_buffer):
        item_id = event["item_id"]
        audio_end_ms = event["audio_end_ms"]
        speech = self.queued_speech_items[item_id]
        speech["audio_end_ms"] = audio_end_ms
        if input_audio_buffer:
            start_index = (speech["audio_start_ms"] * self.default_frequency) // 1000
            end_index = (speech["audio_end_ms"] * self.default_frequency) // 1000
            speech["audio"] = input_audio_buffer[start_index:end_index]
        return None, None

    def _process_response_created(self, event):
        response = event["response"]
        if response["id"] not in self.response_lookup:
            self.response_lookup[response["id"]] = response
            self.responses.append(response)
        return None, None

    def _process_output_item_added(self, event):
        response_id = event["response_id"]
        item = event["item"]
        response = self.response_lookup.get(response_id)
        if not response:
            raise Exception(f"response.output_item.added: Response {response_id} not found")

        response["output"].append(item["id"])
        return None, None

    def _process_output_item_done(self, event):
        item = event["item"]
        if not item:
            raise Exception('response.output_item.done: Missing "item"')

        found_item = self.item_lookup.get(item["id"])
        if not found_item:
            raise Exception(f'response.output_item.done: Item "{item["id"]}" not found')

        found_item["status"] = item["status"]
        return found_item, None

    def _process_content_part_added(self, event):
        item_id = event["item_id"]
        part = event["part"]
        item = self.item_lookup.get(item_id)
        if not item:
            raise Exception(f'response.content_part.added: Item "{item_id}" not found')

        item["content"].append(part)
        return item, None

    def _process_audio_transcript_delta(self, event):
        item_id = event["item_id"]
        content_index = event["content_index"]
        delta = event["delta"]
        item = self.item_lookup.get(item_id)
        if not item:
            raise Exception(f'response.audio_transcript.delta: Item "{item_id}" not found')

        item["content"][content_index]["transcript"] += delta
        item["formatted"]["transcript"] += delta
        return item, {"transcript": delta}

    def _process_audio_delta(self, event):
        item_id = event["item_id"]
        content_index = event["content_index"]
        delta = event["delta"]
        item = self.item_lookup.get(item_id)
        if not item:
            # No existing item—just ignore or log
            return None, None

        array_buffer = base64_to_array_buffer(delta)
        audio_bytes = array_buffer.tobytes()
        # You could do PCM16 merging here if your item["formatted"]["audio"] is also PCM16.
        # For now, we just pass the newly received chunk as is.
        return item, {"audio": audio_bytes}

    def _process_text_delta(self, event):
        item_id = event["item_id"]
        content_index = event["content_index"]
        delta = event["delta"]
        item = self.item_lookup.get(item_id)
        if not item:
            raise Exception(f'response.text.delta: Item "{item_id}" not found')

        item["content"][content_index]["text"] += delta
        item["formatted"]["text"] += delta
        return item, {"text": delta}

    def _process_function_call_arguments_delta(self, event):
        item_id = event["item_id"]
        delta = event["delta"]
        item = self.item_lookup.get(item_id)
        if not item:
            raise Exception(f'response.function_call_arguments.delta: Item "{item_id}" not found')

        item["arguments"] += delta
        if "tool" in item["formatted"]:
            item["formatted"]["tool"]["arguments"] += delta
        return item, {"arguments": delta}

#######################################################################
# RealtimeClient
#######################################################################

class RealtimeClient(RealtimeEventHandler):
    """
    High-level client that orchestrates:
    - RealtimeAPI WebSocket connections
    - RealtimeConversation to track conversation state
    - Tools (function calling)
    - Session config (instructions, modalities, voice, etc.)
    """
    def __init__(self, system_prompt: str):
        super().__init__()

        self.logger = logging.getLogger(__name__)

        self.system_prompt = system_prompt
        self.default_session_config = {
            "modalities": ["text", "audio"],
            "instructions": self.system_prompt,
            "voice": "shimmer",
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm16",
            "input_audio_transcription": {"model": "whisper-1"},
            "turn_detection": {"type": "server_vad"},
            "tools": [],
            "tool_choice": "auto",
            "temperature": 0.8,
            "max_response_output_tokens": 4096,
        }
        self.session_config = {}
        self.realtime = RealtimeAPI()
        self.conversation = RealtimeConversation()

        self._reset_config()
        self._add_api_event_handlers()

    def _reset_config(self):
        """
        Reset session state to defaults.
        """
        self.session_created = False
        self.tools = {}
        self.session_config = self.default_session_config.copy()
        self.input_audio_buffer = bytearray()
        return True

    def _add_api_event_handlers(self):
        """
        Hook RealtimeAPI events to process them in RealtimeClient.
        """
        self.realtime.on("client.*", self._log_event)
        self.realtime.on("server.*", self._log_event)

        self.realtime.on("server.session.created", self._on_session_created)
        self.realtime.on("server.response.created", self._process_event)
        self.realtime.on("server.response.output_item.added", self._process_event)
        self.realtime.on("server.response.content_part.added", self._process_event)
        self.realtime.on("server.input_audio_buffer.speech_started", self._on_speech_started)
        self.realtime.on("server.input_audio_buffer.speech_stopped", self._on_speech_stopped)
        self.realtime.on("server.conversation.item.created", self._on_item_created)
        self.realtime.on("server.conversation.item.truncated", self._process_event)
        self.realtime.on("server.conversation.item.deleted", self._process_event)
        self.realtime.on("server.conversation.item.input_audio_transcription.completed", self._process_event)
        self.realtime.on("server.response.audio_transcript.delta", self._process_event)
        self.realtime.on("server.response.audio.delta", self._process_event)
        self.realtime.on("server.response.text.delta", self._process_event)
        self.realtime.on("server.response.function_call_arguments.delta", self._process_event)
        self.realtime.on("server.response.output_item.done", self._on_output_item_done)

    def _log_event(self, event):
        # Log or dispatch events for debugging
        realtime_event = {
            "time": datetime.utcnow().isoformat(),
            "source": "client" if event["type"].startswith("client.") else "server",
            "event": event,
        }
        self.dispatch("realtime.event", realtime_event)

    def _on_session_created(self, event):
        self.session_created = True

    def _process_event(self, event, *args):
        # Pass event to RealtimeConversation
        item, delta = self.conversation.process_event(event, *args)
        # For specific events, we re-dispatch to local handlers
        if event["type"] == "conversation.item.input_audio_transcription.completed":
            self.dispatch("conversation.item.input_audio_transcription.completed", {"item": item, "delta": delta})
        if item:
            self.dispatch("conversation.updated", {"item": item, "delta": delta})
        return item, delta

    def _on_speech_started(self, event):
        self._process_event(event)
        self.dispatch("conversation.interrupted", event)

    def _on_speech_stopped(self, event):
        self._process_event(event, self.input_audio_buffer)

    def _on_item_created(self, event):
        item, delta = self._process_event(event)
        self.dispatch("conversation.item.appended", {"item": item})
        if item and item["status"] == "completed":
            self.dispatch("conversation.item.completed", {"item": item})

    async def _on_output_item_done(self, event):
        item, delta = self._process_event(event)
        if item and item["status"] == "completed":
            self.dispatch("conversation.item.completed", {"item": item})
        # If item was a function call, we handle that here
        if item and item.get("formatted", {}).get("tool"):
            await self._call_tool(item["formatted"]["tool"])

    async def _call_tool(self, tool):
        """
        Invokes the Python handler for the requested tool name with JSON arguments.
        Then returns the result back to Azure as a function_call_output item.
        """
        try:
            self.logger.info(f"Function call: {tool['name']} with arguments={tool['arguments']}")
            json_arguments = json.loads(tool["arguments"])
            tool_config = self.tools.get(tool["name"])
            if not tool_config:
                raise Exception(f'Tool "{tool["name"]}" not found')

            handler_result = await tool_config["handler"](**json_arguments)

            # Send result back to Azure
            await self.realtime.send("conversation.item.create", {
                "item": {
                    "type": "function_call_output",
                    "call_id": tool["call_id"],
                    "output": json.dumps(handler_result),
                }
            })
        except Exception as e:
            self.logger.error(traceback.format_exc())
            # Send the error as function_call_output
            await self.realtime.send("conversation.item.create", {
                "item": {
                    "type": "function_call_output",
                    "call_id": tool["call_id"],
                    "output": json.dumps({"error": str(e)}),
                }
            })
        await self.create_response()

    #######################################################################
    # Public Methods
    #######################################################################

    def is_connected(self):
        return self.realtime.is_connected()

    def reset(self):
        """Reset the entire client, closing any existing connections."""
        self.disconnect()
        self.realtime.clear_event_handlers()
        self._reset_config()
        self._add_api_event_handlers()
        return True

    async def connect(self):
        """Connect to the Azure Realtime endpoint."""
        if self.is_connected():
            raise Exception("Already connected, use .disconnect() first")
        await self.realtime.connect()
        await self.update_session()
        return True

    async def wait_for_session_created(self):
        """Block until 'server.session.created' event arrives."""
        if not self.is_connected():
            raise Exception("Not connected, use .connect() first")
        while not self.session_created:
            await asyncio.sleep(0.001)
        return True

    async def disconnect(self):
        """Disconnect from Azure and clear conversation."""
        self.session_created = False
        self.conversation.clear()
        if self.realtime.is_connected():
            await self.realtime.disconnect()

    def get_turn_detection_type(self):
        return self.session_config.get("turn_detection", {}).get("type")

    async def add_tool(self, definition, handler):
        """
        Register a function-based tool. 
        'definition' is a dict with name/description/parameters.
        'handler' is an async function that executes the tool logic.
        """
        name = definition.get("name")
        if not name:
            raise Exception("Tool definition is missing a 'name'")

        if name in self.tools:
            raise Exception(f'Tool "{name}" already added. Remove it before re-adding.')

        if not callable(handler):
            raise Exception(f'Tool "{name}" handler must be a callable/async function')

        self.tools[name] = {"definition": definition, "handler": handler}
        await self.update_session()
        return self.tools[name]

    def remove_tool(self, name):
        """Remove a registered tool by name."""
        if name not in self.tools:
            raise Exception(f'Tool "{name}" does not exist.')
        del self.tools[name]
        return True

    async def delete_item(self, item_id):
        """Delete a conversation item from Azure Realtime."""
        await self.realtime.send("conversation.item.delete", {"item_id": item_id})
        return True

    async def update_session(self, **kwargs):
        """Send updated session config (instructions, voice, tools, etc.) to Azure."""
        self.session_config.update(kwargs)

        # Combine built-in 'tools' + user-registered tools
        use_tools = [
            {**tool_def, "type": "function"}
            for tool_def in self.session_config.get("tools", [])
        ] + [
            {**self.tools[key]["definition"], "type": "function"}
            for key in self.tools
        ]

        session = {**self.session_config, "tools": use_tools}

        if self.realtime.is_connected():
            await self.realtime.send("session.update", {"session": session})

        return True

    async def create_conversation_item(self, item):
        """Create an item in the conversation, e.g. a user or system message."""
        await self.realtime.send("conversation.item.create", {"item": item})

    async def send_user_message_content(self, content=[]):
        """
        Send a user message with text or audio content. 
        e.g. content=[{"type": "input_text", "text": "Hello"}]
        """
        if content:
            # Convert raw audio to base64 if present
            for c in content:
                if c["type"] == "input_audio" and isinstance(c.get("audio"), (bytes, bytearray)):
                    c["audio"] = array_buffer_to_base64(np.array(c["audio"]))
            # Create the item
            await self.realtime.send("conversation.item.create", {
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": content
                }
            })
        # After sending user message, create a response from Azure
        await self.create_response()
        return True

    async def append_input_audio(self, array_buffer):
        """
        Append raw audio bytes to the server. 
        If turn detection is disabled, we commit the audio buffer after each chunk.
        """
        if len(array_buffer) > 0:
            await self.realtime.send("input_audio_buffer.append", {
                "audio": array_buffer_to_base64(np.array(array_buffer)),
            })
            self.input_audio_buffer.extend(array_buffer)
        return True

    async def create_response(self):
        """
        Ask Azure to generate a new response. 
        If turn detection is None, we also finalize the audio buffer (input_audio_buffer.commit).
        """
        if self.get_turn_detection_type() is None and len(self.input_audio_buffer) > 0:
            await self.realtime.send("input_audio_buffer.commit")
            self.conversation.queue_input_audio(self.input_audio_buffer)
            self.input_audio_buffer = bytearray()

        await self.realtime.send("response.create")
        return True

    async def cancel_response(self, item_id=None, sample_count=0):
        """
        Cancel the ongoing response generation. 
        If item_id is provided, we also truncate the existing audio in that item.
        """
        if not item_id:
            await self.realtime.send("response.cancel")
            return {"item": None}

        # Find the item
        item = self.conversation.get_item(item_id)
        if not item:
            raise Exception(f'Could not find item "{item_id}"')

        if item["type"] != "message" or item["role"] != "assistant":
            raise Exception("Can only cancel assistant messages")

        # Cancel the response
        await self.realtime.send("response.cancel")

        audio_index = next((i for i, c in enumerate(item["content"]) if c["type"] == "audio"), -1)
        if audio_index == -1:
            raise Exception("No audio content found on item to truncate")

        await self.realtime.send("conversation.item.truncate", {
            "item_id": item_id,
            "content_index": audio_index,
            "audio_end_ms": int((sample_count / self.conversation.default_frequency) * 1000),
        })
        return {"item": item}

    async def wait_for_next_item(self):
        """ Wait for the next 'conversation.item.appended' event. """
        event = await self.wait_for_next("conversation.item.appended")
        return {"item": event["item"]}

    async def wait_for_next_completed_item(self):
        """ Wait for the next 'conversation.item.completed' event. """
        event = await self.wait_for_next("conversation.item.completed")
        return {"item": event["item"]}
