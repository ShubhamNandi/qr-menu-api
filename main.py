#!/usr/bin/env python3
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import json
import os
import uuid
import io
import zipfile
import socket
import time
from pathlib import Path
import qrcode
try:
    import netifaces
except ImportError:
    netifaces = None

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

# QR Code Configuration
FRONTEND_PORT = os.getenv("FRONTEND_PORT", "9111")
FRONTEND_BASE_URL_CACHE = {"url": None, "timestamp": 0}
CACHE_TTL = 30  # Cache IP for 30 seconds

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


class TableMappingCreate(BaseModel):
    token: str
    table_number: int


class TableMappingUpdate(BaseModel):
    table_number: int


class TableMappingBulk(BaseModel):
    mappings: dict  # {token: table_number}


class TableConfig(BaseModel):
    total_tables: int


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


def generate_table_token(table_number: int) -> str:
    """Generate a unique token for a table"""
    # Generate a short unique token using UUID
    short_uuid = str(uuid.uuid4()).replace('-', '')[:12]
    return f"table{table_number}_token_{short_uuid}"


def get_ip():
    """
    Get IP address from the first available network interface.
    Prioritizes wireless interfaces (wlan0, wlp3s0) then wired interfaces (eth0, enp2s0).
    Falls back to socket method if netifaces is not available.
    """
    # Try netifaces method first (more reliable)
    if netifaces:
        try:
            interface_patterns = [
                lambda x: x.startswith('wl'),     # Wireless: wlan0, wlp3s0
                lambda x: x.startswith('en'),     # Wired: enp2s0, eno1
                lambda x: x.startswith('eth'),    # Wired: eth0
                lambda x: x.startswith('usb')     # USB ethernet
            ]
            
            skip_patterns = [
                'lo', 'docker', 'veth', 'br-', 'tun', 'vmnet'
            ]

            interfaces = netifaces.interfaces()
            
            for pattern_func in interface_patterns:
                for interface in interfaces:
                    if any(interface.startswith(pattern) for pattern in skip_patterns):
                        continue
                        
                    if pattern_func(interface):
                        addresses = netifaces.ifaddresses(interface)
                        if netifaces.AF_INET in addresses:
                            ip = addresses[netifaces.AF_INET][0]['addr']
                            if ip and ip != "":
                                try:
                                    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                                        s.settimeout(1)
                                        s.connect(("8.8.8.8", 53))
                                        return ip
                                except:
                                    continue
        except Exception:
            pass
    
    # Fallback: socket method
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(1)
            s.connect(("8.8.8.8", 53))
            ip = s.getsockname()[0]
            if ip and ip != "127.0.0.1":
                return ip
    except Exception:
        pass
    
    return None


def get_frontend_url():
    """
    Get frontend URL dynamically with caching.
    Checks IP every CACHE_TTL seconds to handle WiFi changes.
    """
    current_time = time.time()
    
    # Check cache validity
    if (FRONTEND_BASE_URL_CACHE["url"] and 
        (current_time - FRONTEND_BASE_URL_CACHE["timestamp"]) < CACHE_TTL):
        return FRONTEND_BASE_URL_CACHE["url"]
    
    # Get fresh IP
    ip = get_ip()
    
    if ip:
        frontend_url = f"http://{ip}:{FRONTEND_PORT}"
        FRONTEND_BASE_URL_CACHE["url"] = frontend_url
        FRONTEND_BASE_URL_CACHE["timestamp"] = current_time
        return frontend_url
    else:
        # Fallback to environment variable or default
        fallback = os.getenv("FRONTEND_URL", "http://192.168.0.137:9111")
        FRONTEND_BASE_URL_CACHE["url"] = fallback
        FRONTEND_BASE_URL_CACHE["timestamp"] = current_time
        return fallback


def generate_qr_code_image(url: str, size: int = 10, border: int = 4) -> bytes:
    """Generate QR code image as PNG bytes"""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=size,
        border=border,
    )
    qr.add_data(url)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Convert to bytes
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    return img_bytes.getvalue()


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


# Admin Endpoints for Table Management
@app.get("/api/qr-menu/admin/tables")
async def get_all_tables():
    """Get all table mappings (admin only)"""
    mapping = load_table_mapping()
    # Convert to list format for easier frontend consumption
    tables = [{"token": token, "table_number": table_num} for token, table_num in mapping.items()]
    # Sort by table number
    tables.sort(key=lambda x: x["table_number"])
    return {
        "tables": tables,
        "total": len(tables)
    }


@app.post("/api/qr-menu/admin/tables/configure")
async def configure_tables(config: TableConfig):
    """Configure total number of tables - auto-generates tokens and mappings (admin only)"""
    if config.total_tables < 1:
        raise HTTPException(status_code=400, detail="Total tables must be at least 1")
    
    if config.total_tables > 100:
        raise HTTPException(status_code=400, detail="Total tables cannot exceed 100")
    
    # Generate new mappings
    new_mapping = {}
    for table_num in range(1, config.total_tables + 1):
        token = generate_table_token(table_num)
        new_mapping[token] = table_num
    
    # Save the new mapping (replaces all existing)
    save_table_mapping(new_mapping)
    
    # Convert to list format for response
    tables = [{"token": token, "table_number": table_num} for token, table_num in new_mapping.items()]
    tables.sort(key=lambda x: x["table_number"])
    
    return {
        "message": f"Successfully configured {config.total_tables} table(s)",
        "total_tables": config.total_tables,
        "tables": tables
    }


# QR Code Generation Endpoints
@app.get("/api/qr-menu/admin/qr-code/{table_number}")
async def get_qr_code_for_table(table_number: int):
    """Generate QR code for a specific table (admin only)"""
    mapping = load_table_mapping()
    
    # Find token for this table number
    token = next((t for t, tn in mapping.items() if tn == table_number), None)
    if token is None:
        raise HTTPException(status_code=404, detail=f"Table {table_number} not found")
    
    # Generate QR code URL
    qr_url = f"{get_frontend_url()}?t={token}"
    
    # Generate QR code image
    qr_image = generate_qr_code_image(qr_url)
    
    return Response(
        content=qr_image,
        media_type="image/png",
        headers={
            "Content-Disposition": f"attachment; filename=table_{table_number}_qr_code.png"
        }
    )


@app.get("/api/qr-menu/admin/qr-codes/all")
async def get_all_qr_codes():
    """Generate QR codes for all tables as a ZIP file (admin only)"""
    mapping = load_table_mapping()
    
    if not mapping:
        raise HTTPException(status_code=404, detail="No tables configured. Please configure tables first.")
    
    # Create ZIP file in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for token, table_number in mapping.items():
            # Generate QR code URL
            qr_url = f"{get_frontend_url()}?t={token}"
            
            # Generate QR code image
            qr_image = generate_qr_code_image(qr_url)
            
            # Add to ZIP
            zip_file.writestr(f"table_{table_number}_qr_code.png", qr_image)
    
    zip_buffer.seek(0)
    
    return Response(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": "attachment; filename=all_table_qr_codes.zip"
        }
    )


@app.get("/api/qr-menu/admin/qr-codes/info")
async def get_qr_codes_info():
    """Get QR code URLs for all tables (admin only)"""
    mapping = load_table_mapping()
    
    tables_info = []
    frontend_url = get_frontend_url()
    for token, table_number in sorted(mapping.items(), key=lambda x: x[1]):
        qr_url = f"{frontend_url}?t={token}"
        tables_info.append({
            "table_number": table_number,
            "token": token,
            "qr_url": qr_url
        })
    
    return {
        "frontend_url": frontend_url,
        "tables": tables_info,
        "total": len(tables_info)
    }


@app.post("/api/qr-menu/admin/tables")
async def create_table_mapping(table_mapping: TableMappingCreate):
    """Add a new table mapping (admin only)"""
    mapping = load_table_mapping()
    
    # Check if token already exists
    if table_mapping.token in mapping:
        raise HTTPException(
            status_code=400, 
            detail=f"Token '{table_mapping.token}' already exists for table {mapping[table_mapping.token]}"
        )
    
    # Check if table number already exists
    existing_table = next((token for token, table_num in mapping.items() if table_num == table_mapping.table_number), None)
    if existing_table:
        raise HTTPException(
            status_code=400,
            detail=f"Table number {table_mapping.table_number} already exists with token '{existing_table}'"
        )
    
    # Add new mapping
    mapping[table_mapping.token] = table_mapping.table_number
    save_table_mapping(mapping)
    
    return {
        "message": "Table mapping created successfully",
        "token": table_mapping.token,
        "table_number": table_mapping.table_number
    }


@app.put("/api/qr-menu/admin/tables/{token}")
async def update_table_mapping(token: str, update: TableMappingUpdate):
    """Update table number for an existing token (admin only)"""
    mapping = load_table_mapping()
    
    # Check if token exists
    if token not in mapping:
        raise HTTPException(status_code=404, detail="Token not found")
    
    # Check if new table number already exists (and is not the current one)
    existing_token = next((t for t, table_num in mapping.items() if table_num == update.table_number and t != token), None)
    if existing_token:
        raise HTTPException(
            status_code=400,
            detail=f"Table number {update.table_number} already exists with token '{existing_token}'"
        )
    
    # Update mapping
    old_table_number = mapping[token]
    mapping[token] = update.table_number
    save_table_mapping(mapping)
    
    return {
        "message": "Table mapping updated successfully",
        "token": token,
        "old_table_number": old_table_number,
        "new_table_number": update.table_number
    }


@app.delete("/api/qr-menu/admin/tables/{token}")
async def delete_table_mapping(token: str):
    """Delete a table mapping (admin only)"""
    mapping = load_table_mapping()
    
    # Check if token exists
    if token not in mapping:
        raise HTTPException(status_code=404, detail="Token not found")
    
    # Get table number before deletion
    table_number = mapping[token]
    
    # Delete mapping
    del mapping[token]
    save_table_mapping(mapping)
    
    return {
        "message": "Table mapping deleted successfully",
        "token": token,
        "table_number": table_number
    }


@app.post("/api/qr-menu/admin/tables/bulk")
async def bulk_update_tables(bulk: TableMappingBulk):
    """Bulk update table mappings (admin only) - replaces all existing mappings"""
    # Validate all mappings
    table_numbers = list(bulk.mappings.values())
    if len(table_numbers) != len(set(table_numbers)):
        raise HTTPException(
            status_code=400,
            detail="Duplicate table numbers found. Each table number must be unique."
        )
    
    # Save new mappings (replaces all existing)
    save_table_mapping(bulk.mappings)
    
    return {
        "message": "Table mappings updated successfully",
        "total_tables": len(bulk.mappings),
        "mappings": bulk.mappings
    }


