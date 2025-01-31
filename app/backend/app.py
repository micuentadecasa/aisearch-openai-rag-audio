import logging
import os
from pathlib import Path
from aiohttp import web
from azure.core.credentials import AzureKeyCredential
from dotenv import load_dotenv
from rtmt import RTMiddleTier
import json

def static_rag_tool(query):
    """Simulated RAG function returning static results."""
    static_data = {
        "query": query,
        "results": [
            {"title": "Sample Document 1", "content": "This is a relevant piece of information."},
            {"title": "Sample Document 2", "content": "Another useful document snippet."}
        ]
    }
    return json.dumps(static_data)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("voicerag")

async def create_app():
    load_dotenv()

    llm_key = os.environ.get("AZURE_OPENAI_API_KEY")
    
    app = web.Application()

    rtmt = RTMiddleTier(
        endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        deployment=os.environ["AZURE_OPENAI_REALTIME_DEPLOYMENT"],
        api_key=llm_key,
        voice_choice=os.environ.get("AZURE_OPENAI_REALTIME_VOICE_CHOICE") or "alloy"
    )

    rtmt.system_message = """
        You are a helpful assistant. When asked about external knowledge, retrieve data using the 'search' tool.
    """.strip()

    rtmt.register_tool("search", static_rag_tool, {"type": "object", "properties": {"query": {"type": "string"}}})

    rtmt.attach_to_app(app, "/realtime")

    current_directory = Path(__file__).parent
    app.add_routes([web.get('/', lambda _: web.FileResponse(current_directory / 'static/index.html'))])
    app.router.add_static('/', path=current_directory / 'static', name='static')

    return app

if __name__ == "__main__":
    web.run_app(create_app(), host="localhost", port=8765)