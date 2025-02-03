import re
from typing import Any

from rtmt import RTMiddleTier, Tool, ToolResult, ToolResultDirection

# Optionally, if you intended to use the two sets of car data, decide which one is your source.
# For example, here we use STATIC_CAR_DATA as the definitive list.
STATIC_CAR_DATA = [
    {"id": "1", "name": "Tesla Model S", "details": "Electric, luxury sedan"},
    {"id": "2", "name": "Ford Mustang", "details": "Iconic American muscle car"},
    {"id": "3", "name": "Toyota Corolla", "details": "Reliable and fuel efficient"},
    # add more entries as needed...
]

# Tool schema for searchCars.
_car_tool_schema = {
    "type": "function",
    "name": "searchCars",
    "description": "Search a static list of cars. Provide a search query to match against car names or details.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query to filter car data"
            }
        },
        "required": ["query"],
        "additionalProperties": False   #// Consider changing this to True if extra keys might be present.
    }
}

import logging

logger = logging.getLogger("CarTool")

async def _search_car_tool(args: Any) -> ToolResult:
    # Ensure the query is a string and in lower-case for matching.
    query = str(args.get("query", "")).lower()
    logger.info("searchCars tool invoked with query: %s", query)
    print("_search_car_tool")
    results = []
    for car in STATIC_CAR_DATA:
        if query in car["name"].lower() or query in car["details"].lower():
            results.append(f"[{car['id']}]: {car['name']} - {car['details']}")
    if results:
        result_text = "\n-----\n".join(results)
        logger.info("searchCars result: %s", result_text)
        return ToolResult(result_text, ToolResultDirection.TO_SERVER)
    else:
        logger.info("searchCars found no results for query: %s", query)
        return ToolResult("No matching cars found.", ToolResultDirection.TO_CLIENT)

def attach_car_tools(rtmt: RTMiddleTier) -> None:
    print("attach_car_tools")
    # Register the tool with its schema and target function.
    rtmt.tools["searchCars"] = Tool(schema=_car_tool_schema, target=lambda args: _search_car_tool(args))
