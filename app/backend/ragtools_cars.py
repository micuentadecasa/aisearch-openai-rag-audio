import re
from typing import Any

from azure.core.credentials import AzureKeyCredential
from azure.identity import DefaultAzureCredential
from azure.search.documents.aio import SearchClient
from azure.search.documents.models import VectorizableTextQuery

from rtmt import RTMiddleTier, Tool, ToolResult, ToolResultDirection

# Static data for car information
car_data = [
    {"color": "red", "model": "Sedan", "description": "A red sedan with excellent fuel efficiency."},
    {"color": "blue", "model": "SUV", "description": "A blue SUV with spacious interior and advanced safety features."}
]

_car_search_tool_schema = {
    "type": "function",
    "name": "search_cars",
    "description": "Search for car information. Results are formatted as a color, model, and description.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query for car information"
            }
        },
        "required": ["query"],
        "additionalProperties": False
    }
}

async def _car_search_tool(args: Any) -> ToolResult:
    print("_car_search_tool")
    query = args['query'].lower()
    result = ""
    for car in car_data:
        if query in car['color'].lower() or query in car['model'].lower():
            result += f"Color: {car['color']}, Model: {car['model']}, Description: {car['description']}\n-----\n"
            print(result)
    return ToolResult(result, ToolResultDirection.TO_CLIENT)

def attach_car_tools(rtmt: RTMiddleTier) -> None:
    print("attach_car_tools")
    rtmt.tools["search_cars"] = Tool(schema=_car_search_tool_schema, target=lambda args: _car_search_tool(args))
