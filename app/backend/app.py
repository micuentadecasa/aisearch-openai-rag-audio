import logging
import os
from pathlib import Path
from aiohttp import web
from azure.core.credentials import AzureKeyCredential
from dotenv import load_dotenv
from rtmt import RTMiddleTier
import json


 
from ragtools_cars import attach_car_tools
 
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("voicerag")

logger.debug("starting the websocket server")
print("starting")

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
        You are a helpful assistant. Only answer questions accessible with the 'search' tool. 
        The user is listening to answers with audio, so it's *super* important that answers are as short as possible, a single sentence if at all possible. 
        Never read file names or source names or keys out loud. 
        Always use the following step-by-step instructions to respond: 
        1. The user will ask you about cars, and you should use the search_cars tool to return information. Always use the 'search_cars' tool to check the knowledge base before answering a question. 
        always that you use this tool tell it to the client. if you cannot use the search_cars tool tell it to the client.
        2. Produce an answer that's as short as possible. If the answer isn't in the knowledge base, say you don't know.  
    """.strip()


    attach_car_tools(rtmt)

    rtmt.attach_to_app(app, "/realtime")

    current_directory = Path(__file__).parent
    app.add_routes([web.get('/', lambda _: web.FileResponse(current_directory / 'static/index.html'))])
    app.router.add_static('/', path=current_directory / 'static', name='static')

    return app

if __name__ == "__main__":
    web.run_app(create_app(), host="localhost", port=8765)
