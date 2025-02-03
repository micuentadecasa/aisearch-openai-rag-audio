import json
import chainlit as cl
from datetime import datetime
import random

"""
Here we define a small mock database in Python dictionaries:
 - We have 2 customers: c1, c2
 - We have 2 products: p1, p2
 - Each customer can have zero or more of these products assigned
"""

# Simple data structure:
CUSTOMERS = {
    "c1": {
        "membership_level": "Gold",
        "account_status": "Active",
        # The user 'c1' has both p1 and p2
        "orders": {
            "p1": {"name": "Wireless Earbuds", "price": 79.99, "status": "Shipped"},
            "p2": {"name": "Laptop Backpack", "price": 49.99, "status": "Pending"},
        }
    },
    "c2": {
        "membership_level": "Silver",
        "account_status": "Pending",
        # The user 'c2' only has p1
        "orders": {
            "p1": {"name": "Wireless Earbuds", "price": 79.99, "status": "Delivered"},
        }
    }
}

# ----------------------------------------------------------
# Tool Definition: get_customer_orders
# ----------------------------------------------------------
get_customer_orders_def = {
    "name": "get_customer_orders",
    "description": "Return all products/orders that belong to a given customer",
    "parameters": {
        "type": "object",
        "properties": {
            "customer_id": {
                "type": "string",
                "description": "The ID of the customer, e.g. 'c1' or 'c2'"
            }
        },
        "required": ["customer_id"]
    }
}

async def get_customer_orders_handler(customer_id):
    """
    Return a string listing all of the products that belong to this customer.
    If the customer doesn't exist, return a 'not found' message.
    """

    customer = CUSTOMERS.get(customer_id)
    if not customer:
        return f"Customer '{customer_id}' not found."

    # Gather the orders for this user
    orders = customer["orders"]
    if not orders:
        return f"Customer '{customer_id}' has no products."

    # Build a readable string listing all items
    # Each item has a name, price, status, etc.
    lines = []
    for product_id, details in orders.items():
        name = details["name"]
        price = details["price"]
        status = details["status"]
        lines.append(f" - {product_id}: {name}, price={price}, status={status}")

    result_str = "\n".join(lines)
    return f"Customer '{customer_id}' has the following orders:\n{result_str}"


# ----------------------------------------------------------
# Example: Another tool (Optional)
# ----------------------------------------------------------
# Just to illustrate how you can have multiple tools:
update_account_info_def = {
    "name": "update_account_info",
    "description": "Update a customer's account status to a new value (Active, Pending, etc.)",
    "parameters": {
        "type": "object",
        "properties": {
            "customer_id": {
                "type": "string",
                "description": "Customer ID, e.g. 'c1' or 'c2'"
            },
            "new_status": {
                "type": "string",
                "description": "The new account status, e.g. 'Active' or 'Pending'"
            }
        },
        "required": ["customer_id", "new_status"]
    }
}

async def update_account_info_handler(customer_id, new_status):
    """
    Example tool that updates the 'account_status' for a given user.
    """
    customer = CUSTOMERS.get(customer_id)
    if not customer:
        return f"Customer '{customer_id}' not found."
    old_status = customer["account_status"]
    customer["account_status"] = new_status
    return (f"Customer '{customer_id}' account status changed from "
            f"'{old_status}' to '{new_status}'.")


# ----------------------------------------------------------
# Tools List
# ----------------------------------------------------------
# This is what you'll register with your RealtimeClient
tools = [
    (get_customer_orders_def, get_customer_orders_handler),
    (update_account_info_def, update_account_info_handler)
]
