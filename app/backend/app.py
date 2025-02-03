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

    # Update the system instructions to be explicit about the tool call format.
    rtmt.system_message = """
You are a helpful assistant specialised in car information.
When the user asks about cars, you must not provide a direct text answer.
Instead, you must output a function call in JSON with the following format:
{
  "function": "searchCars",
  "parameters": {
    "query": "<search query>"
  }
}
If no matching car data is found, reply with: "No matching cars found."
Keep your answer as concise as possible.
    """.strip()

    # Attach the car tool so that the middleware can invoke it.
    attach_car_tools(rtmt)

    rtmt.attach_to_app(app, "/realtime")

    current_directory = Path(__file__).parent
    app.add_routes([web.get('/', lambda _: web.FileResponse(current_directory / 'static/index.html'))])
    app.router.add_static('/', path=current_directory / 'static', name='static')

    return app

if __name__ == "__main__":
    web.run_app(create_app(), host="localhost", port=8765)
