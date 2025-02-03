import re
from typing import Any
 

from rtmt import RTMiddleTier, Tool, ToolResult, ToolResultDirection

# Static data for car information
car_data = [
    {"color": "red", "model": "Sedan", "description": "A red sedan with excellent fuel efficiency."},
    {"color": "blue", "model": "SUV", "description": "A blue SUV with spacious interior and advanced safety features."}
]

# Define static list of cars
STATIC_CAR_DATA = [
    {"id": "1", "name": "Tesla Model S", "details": "Electric, luxury sedan"},
    {"id": "2", "name": "Ford Mustang", "details": "Iconic American muscle car"},
    {"id": "3", "name": "Toyota Corolla", "details": "Reliable and fuel efficient"},
    # add more entries as needed...
]
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
        "additionalProperties": False
    }
}

import logging

logger = logging.getLogger("CarTool")

async def _search_car_tool(args: any) -> ToolResult:
    query = args.get("query", "").lower()
    logger.info("searchCars tool invoked with query: %s", query)
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
        return ToolResult("No matching cars found.", ToolResultDirection.TO_SERVER)

def attach_car_tools(rtmt: RTMiddleTier) -> None:
    print("attach_car_tools")
    rtmt.tools["searchCars"] = Tool(schema=_car_tool_schema, target=lambda args: _search_car_tool(args))

