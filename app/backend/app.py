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
    You are a helpful assistant. Only answer questions by using the 'searchCars' tool to check the static car data.
    The user listens to the answers as audio, so your responses must be as short as possible—a single sentence if possible.
    Never read out loud any file names, source names, or keys.
    Follow these instructions step-by-step:
    1. When the user asks about cars, always invoke the 'searchCars' tool to search the static list. Clearly indicate in your answer that you used this tool.
    If you cannot find any matching information with 'searchCars', state that you don't know.
    2. Always produce an answer that is as concise as possible.
    """.strip()


    attach_car_tools(rtmt)

    rtmt.attach_to_app(app, "/realtime")

    current_directory = Path(__file__).parent
    app.add_routes([web.get('/', lambda _: web.FileResponse(current_directory / 'static/index.html'))])
    app.router.add_static('/', path=current_directory / 'static', name='static')

    return app

if __name__ == "__main__":
    web.run_app(create_app(), host="localhost", port=8765)
