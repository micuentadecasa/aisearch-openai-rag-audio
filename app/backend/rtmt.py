import asyncio
import json
import logging
from enum import Enum
from typing import Any, Callable, Optional

import aiohttp
from aiohttp import web

logger = logging.getLogger("voicerag")

class ToolResultDirection(Enum):
    TO_SERVER = 1
    TO_CLIENT = 2

class ToolResult:
    text: str
    destination: ToolResultDirection

    def __init__(self, text: str, destination: ToolResultDirection):
        self.text = text
        self.destination = destination

    def to_text(self) -> str:
        if self.text is None:
            return ""
        return self.text if isinstance(self.text, str) else json.dumps(self.text)

class Tool:
    def __init__(self, target: Any, schema: Any):
        self.target = target
        self.schema = schema

class RTToolCall:
    def __init__(self, tool_call_id: str, previous_id: str):
        self.tool_call_id = tool_call_id
        self.previous_id = previous_id

class RTMiddleTier:
    def __init__(
        self,
        endpoint: str,
        deployment: str,
        api_key: Optional[str],
        voice_choice: Optional[str] = None,
        api_version: str = "2024-10-01-preview"
    ):
        self.endpoint = endpoint
        self.deployment = deployment
        self.api_key = api_key
        self.voice_choice = voice_choice
        self.api_version = api_version
        self.tools = {}
        self._tools_pending = {}
        self.model = None
        self.system_message = None
        self.temperature = None
        self.max_tokens = None
        self.disable_audio = None

    async def _process_message_to_client(self, msg: str, client_ws: web.WebSocketResponse, server_ws: web.WebSocketResponse) -> Optional[str]:
        message = json.loads(msg)
        updated_message = msg
        if message is not None:
            mtype = message["type"]

            if mtype in ["session.created", "response.done"]:
                # This is just an example of removing function calls from returning to the client
                if mtype == "response.done":
                    self._tools_pending.clear()
            elif mtype == "response.output_item.added":
                if "item" in message and message["item"]["type"] == "function_call":
                    updated_message = None
            elif mtype == "conversation.item.created":
                # When we see function calls, stash them
                if "item" in message and message["item"]["type"] == "function_call":
                    call_id = message["item"]["call_id"]
                    self._tools_pending[call_id] = RTToolCall(call_id, message["previous_item_id"])
                    updated_message = None
            elif mtype == "response.function_call_arguments.done":
                updated_message = None
            elif mtype == "response.output_item.done":
                if "item" in message and message["item"]["type"] == "function_call":
                    item = message["item"]
                    call_id = item["call_id"]
                    # Execute server-side tool, if any
                    tool = self.tools.get(item["name"])
                    if not tool:
                        updated_message = None
                    else:
                        args = item["arguments"]
                        result = await tool.target(json.loads(args))
                        await server_ws.send_json({
                            "type": "conversation.item.create",
                            "item": {
                                "type": "function_call_output",
                                "call_id": item["call_id"],
                                "output": result.to_text() if result.destination == ToolResultDirection.TO_SERVER else ""
                            }
                        })
                        if result.destination == ToolResultDirection.TO_CLIENT:
                            await client_ws.send_json({
                                "type": "extension.middle_tier_tool_response",
                                "previous_item_id": self._tools_pending[call_id].previous_id,
                                "tool_name": item["name"],
                                "tool_result": result.to_text()
                            })
                        updated_message = None

        return updated_message

    async def _process_message_to_server(self, msg: str, ws: web.WebSocketResponse) -> Optional[str]:
        message = json.loads(msg)
        updated_message = msg
        if message is not None:
            mtype = message["type"]
            if mtype == "session.update":
                session = message["session"]
                if self.system_message is not None:
                    session["instructions"] = self.system_message
                if self.temperature is not None:
                    session["temperature"] = self.temperature
                if self.max_tokens is not None:
                    session["max_response_output_tokens"] = self.max_tokens
                if self.disable_audio is not None:
                    session["disable_audio"] = self.disable_audio
                if self.voice_choice is not None:
                    session["voice"] = self.voice_choice
                message["session"] = session
                updated_message = json.dumps(message)

        return updated_message

    async def _forward_messages(self, client_ws: web.WebSocketResponse):
        # This function will open another WebSocket to the Azure Realtime endpoint using your API key
        base_url = self.endpoint
        async with aiohttp.ClientSession(base_url=base_url) as session:
            params = {"api-version": self.api_version, "deployment": self.deployment}
            headers = {}
            if self.api_key:
                headers["api-key"] = self.api_key

            async with session.ws_connect("/openai/realtime", headers=headers, params=params) as target_ws:

                async def from_client_to_server():
                    async for msg in client_ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            new_msg = await self._process_message_to_server(msg.data, client_ws)
                            if new_msg is not None:
                                await target_ws.send_str(new_msg)
                        else:
                            logger.warning("Unsupported message type from client: %s", msg.type)
                    # Client closed
                    if target_ws:
                        await target_ws.close()

                async def from_server_to_client():
                    async for msg in target_ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            new_msg = await self._process_message_to_client(msg.data, client_ws, target_ws)
                            if new_msg is not None:
                                await client_ws.send_str(new_msg)
                        else:
                            logger.warning("Unsupported message type from server: %s", msg.type)

                try:
                    await asyncio.gather(from_client_to_server(), from_server_to_client())
                except ConnectionResetError:
                    pass

    async def _websocket_handler(self, request: web.Request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await self._forward_messages(ws)
        return ws

    def register_tool(self, name: str, target: Callable, schema: Any):
        self.tools[name] = Tool(target, schema)

    def attach_to_app(self, app: web.Application, path: str):
        app.router.add_get(path, self._websocket_handler)
