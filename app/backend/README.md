


i have done a new version that works separately and uses openai client library and 
works with audio and tools
 
High-Level Diagram
 
      ┌──────────────────┐
      │   Chainlit UI    │
      │ (front-end mic)  │
      └────────┬─────────┘
               │ (1) audio/text
               │
               ▼
      ┌──────────────────┐
      │   chainlit app   │
      │ (main.py events) │
      └────────┬─────────┘
               │ (2) WebSocket
               │
               ▼
      ┌─────────────────────────┐
      │ Local WS Server (server│
      │ .py or app2.py)        │
      │ * uses RealtimeClient *│
      └────────┬───────────────┘
               │ (3) Azure Realtime
               │   via realtime.py
               ▼
      ┌─────────────────────────┐
      │   Azure GPT-4o Model    │
      │  (realtime endpoint)    │
      └────────┬───────────────┘
               │ (4) Partial/final text or audio
               │
               ▼
      ┌─────────────────────────┐
      │ Local WS Server (again) │
      │    ─ (Tool Calls) ─     │
      └────────┬───────────────┘
               │ (5) Tools.py
               │
               ▼
      ┌─────────────────────────┐
      │   Local DB /  in-code   │
      │ dictionary / any logic  │
      └────────┬───────────────┘
               │ (6) function result
               ▼
      ┌─────────────────────────┐
      │ Azure GPT-4o merges     │
      │ function results        │
      └────────┬───────────────┘
               │ (7) final text/audio
               ▼
      ┌─────────────────────────┐
      │ Chainlit UI sees text   │
      │ or hears streamed audio │
      └─────────────────────────┘
Numbered Steps:

The user speaks (or types) in the Chainlit front-end.
Chainlit captures that audio or text and sends it via WebSocket to your local Python server.
The local server uses RealtimeClient (from realtime.py) to forward content to Azure GPT-4o Realtime.
Azure Realtime might send back partial transcripts, partial audio, or function calls. The local server relays partial data back to Chainlit, so the user sees or hears them.
If the model calls a function (like get_customer_orders), your tools.py gets invoked. It looks up or modifies local data (dictionary, DB, etc.).
The function returns a result, which is sent back to Azure Realtime.
Azure merges the function result into the final output (text or audio), which is again streamed to Chainlit and displayed for the user.
Script-by-Script Explanation
Below is a brief explanation of each important file.

1. realtime.py
Purpose: Provides a high-level RealtimeClient that manages:
WebSocket connection to Azure GPT-4o Realtime (RealtimeAPI).
State tracking of conversation items (RealtimeConversation).
Tools/function-calling logic, so the model can call functions by name and JSON parameters.
Key Classes:
RealtimeAPI: Lower-level WebSocket logic (connect, send, receive).
RealtimeConversation: Maintains conversation item structure, partial transcripts, audio buffers.
RealtimeClient: The entrypoint for your app. You create one per user session. It orchestrates session config, function calls, and partial streaming events.
2. tools.py
Purpose: Houses your function definitions and async handlers that the LLM can call.
Structure:
CUSTOMERS: Hard-coded data (like c1, c2).
get_customer_orders_def + get_customer_orders_handler: For retrieving a specific user’s “orders” (i.e. product ownership).
update_account_info_def + update_account_info_handler: Example for changing the account_status.
tools list: Bundles (definition, handler) for easy registration with RealtimeClient.
Usage: After creating your RealtimeClient, do:
python
Copy
Edit
from tools import tools
for tool_def, tool_handler in tools:
    await my_client.add_tool(tool_def, tool_handler)
so the LLM knows about these tools.

3. server.py (or app2.py)
Purpose: A local WebSocket server that Chainlit connects to.
Flow:
Chainlit makes a WS connection → openai_bridge_handler(websocket).
We create a new RealtimeClient.
We await my_client.connect() to Azure.
For each text or binary chunk from the user, we forward it to my_client (e.g. send_user_message_content or append_input_audio).
For partial or final messages from Azure, we stream them back to Chainlit’s WebSocket with text or bytes.
Event Callbacks:
We typically define handle_conversation_updated, handle_item_completed, etc., to catch partial text or audio from the RealtimeClient. Then we forward it to the user’s WebSocket connection.

4. main.py (Chainlit Entry)
Purpose: The Chainlit UI code.
Flow:
On chat start, greet the user.
On @cl.on_audio_start, connect to ws://localhost:8765.
On @cl.on_audio_chunk, send audio bytes to your local server.
On @cl.on_audio_end, optionally send a marker indicating “end of audio.”
Listen for partial or final text or audio from your local server and display/play it in the Chainlit UI.
End-to-End Summary
User opens your Chainlit app in the browser and sees a mic icon.
The user speaks, producing PCM16 audio.
Chainlit fires on_audio_chunk with raw bytes, which you forward to your local server.
The local server passes these audio bytes to the RealtimeClient, which streams them to Azure GPT-4o Realtime.
Azure transcribes partial speech, or decides to produce partial audio. This flows back to the local server, which in turn relays it to Chainlit.
If the user is requesting an action requiring a function call (e.g. “Check my products”), Azure GPT-4o calls the relevant tool in tools.py, providing JSON arguments. If it “invents” an ID or the ID doesn’t match your data, you see a fallback or “not found.”
The tool returns data to Azure, which merges it into the final response.
The final text or audio is displayed and/or played for the user in the Chainlit interface.

