#!/usr/bin/env python3
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import json
import os
import uuid
from pathlib import Path

# Initialize FastAPI app
app = FastAPI(title="QR Menu API", version="1.0.0")

# CORS configuration - allow frontend on port 9111
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:9111", "http://192.168.0.137:9111", "http://127.0.0.1:9111"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# File paths
BASE_DIR = Path(__file__).parent
TABLE_MAPPING_FILE = BASE_DIR / "table-mapping.json"
ORDERS_FILE = BASE_DIR / "qr_menu_orders.json"

# Initialize files if they don't exist
if not TABLE_MAPPING_FILE.exists():
    with open(TABLE_MAPPING_FILE, 'w') as f:
        json.dump({}, f)

if not ORDERS_FILE.exists():
    with open(ORDERS_FILE, 'w') as f:
        json.dump([], f)


# Pydantic models
class OrderItem(BaseModel):
    id: int
    name: str
    description: str
    price: int
    quantity: int
    category: str
    image: str


class OrderCreate(BaseModel):
    table_number: int
    items: List[OrderItem]
    total: int
    timestamp: str
    status: str = "pending"


class OrderUpdate(BaseModel):
    status: str


class OrderResponse(BaseModel):
    order_id: str
    table_number: int
    items: List[OrderItem]
    total: int
    timestamp: str
    status: str


# Helper functions
def load_table_mapping() -> dict:
    """Load table mapping from JSON file"""
    try:
        with open(TABLE_MAPPING_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        return {}


def save_table_mapping(mapping: dict):
    """Save table mapping to JSON file"""
    with open(TABLE_MAPPING_FILE, 'w') as f:
        json.dump(mapping, f, indent=2)


def load_orders() -> List[dict]:
    """Load orders from JSON file"""
    try:
        with open(ORDERS_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        return []


def save_orders(orders: List[dict]):
    """Save orders to JSON file"""
    with open(ORDERS_FILE, 'w') as f:
        json.dump(orders, f, indent=2)


# API Endpoints
@app.get("/")
async def root():
    """Root endpoint"""
    return {"message": "QR Menu API", "version": "1.0.0"}


@app.get("/api/qr-menu/table/{token}")
async def get_table_number(token: str):
    """Get table number from token"""
    mapping = load_table_mapping()
    table_number = mapping.get(token)
    
    if table_number is None:
        raise HTTPException(status_code=404, detail="Invalid token")
    
    return {"table_number": table_number}


@app.post("/api/qr-menu/orders")
async def create_order(order: OrderCreate):
    """Create a new order"""
    orders = load_orders()
    
    # Generate unique order ID
    order_id = str(uuid.uuid4())
    
    # Create order object
    order_data = {
        "order_id": order_id,
        "table_number": order.table_number,
        "items": [item.dict() for item in order.items],
        "total": order.total,
        "timestamp": order.timestamp,
        "status": order.status
    }
    
    # Add to orders list
    orders.append(order_data)
    
    # Save to file
    save_orders(orders)
    
    return {
        "order_id": order_id,
        "message": "Order saved successfully"
    }


@app.get("/api/qr-menu/orders")
async def get_orders(table: Optional[int] = None, status: Optional[str] = None):
    """Get all orders with optional filters"""
    orders = load_orders()
    
    # Apply filters
    if table is not None:
        orders = [o for o in orders if o.get("table_number") == table]
    
    if status is not None:
        orders = [o for o in orders if o.get("status") == status]
    
    # Sort by timestamp (newest first)
    orders.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    
    return orders


@app.patch("/api/qr-menu/orders/{order_id}")
async def update_order_status(order_id: str, update: OrderUpdate):
    """Update order status"""
    orders = load_orders()
    
    # Find order
    order_found = False
    for order in orders:
        if order.get("order_id") == order_id:
            order["status"] = update.status
            order_found = True
            break
    
    if not order_found:
        raise HTTPException(status_code=404, detail="Order not found")
    
    # Save updated orders
    save_orders(orders)
    
    # Return updated order
    updated_order = next((o for o in orders if o.get("order_id") == order_id), None)
    return updated_order


@app.get("/api/qr-menu/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


