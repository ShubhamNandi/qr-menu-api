#!/usr/bin/env python3
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timedelta
import json
import os
import uuid
import io
import zipfile
import socket
import time
import random
from pathlib import Path
import qrcode
import sys
from collections import defaultdict
try:
    import netifaces
except ImportError:
    netifaces = None

# Add the robot data script path to sys.path
ROBOT_DATA_SCRIPT_PATH = Path("/home/socwt/soc/src/path_and_mission_toolkit/scripts")
if str(ROBOT_DATA_SCRIPT_PATH) not in sys.path:
    sys.path.insert(0, str(ROBOT_DATA_SCRIPT_PATH))

# Import RobotDataSummaryGenerator
try:
    from robot_data_python import RobotDataSummaryGenerator
except ImportError:
    RobotDataSummaryGenerator = None

# Initialize FastAPI app
app = FastAPI(title="QR Menu API", version="1.0.0")

# CORS configuration - allow frontend on port 9111 (both HTTP and HTTPS)
# Allow localhost and common local IP patterns
# This is safe for local network use
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|\d+\.\d+\.\d+\.\d+):9111",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# File paths
BASE_DIR = Path(__file__).parent
TABLE_MAPPING_FILE = BASE_DIR / "table-mapping.json"
PIN_MAPPING_FILE = BASE_DIR / "pin-mapping.json"
ORDERS_FILE = BASE_DIR / "qr_menu_orders.json"
ROBOT_DATA_LOG_FILE = Path("/home/socwt/soc/robot_logs/robot_data_log.json")

# QR Code Configuration
FRONTEND_PORT = os.getenv("FRONTEND_PORT", "9111")
FRONTEND_BASE_URL_CACHE = {"url": None, "timestamp": 0}
CACHE_TTL = 30  # Cache IP for 30 seconds

# Initialize files if they don't exist
if not TABLE_MAPPING_FILE.exists():
    with open(TABLE_MAPPING_FILE, 'w') as f:
        json.dump({}, f)

if not PIN_MAPPING_FILE.exists():
    with open(PIN_MAPPING_FILE, 'w') as f:
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
    
    class Config:
        json_schema_extra = {
            "example": {
                "status": "delivered"
            }
        }


class OrderResponse(BaseModel):
    order_id: str
    table_number: int
    items: List[OrderItem]
    total: int
    timestamp: str
    status: str


class ReadyOrderItem(BaseModel):
    """Ready order item for robot delivery system"""
    table_number: str
    order_id: str
    
    class Config:
        json_schema_extra = {
            "example": {
                "table_number": "Table_1",
                "order_id": "abc123-def456-ghi789"
            }
        }


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


def generate_table_pin(existing_pins: set = None) -> str:
    """Generate a unique 4-digit PIN for a table"""
    if existing_pins is None:
        existing_pins = set()
    
    # Generate a random 4-digit PIN
    max_attempts = 1000
    for _ in range(max_attempts):
        pin = f"{random.randint(1000, 9999)}"
        if pin not in existing_pins:
            return pin
    
    # Fallback: if all 4-digit PINs are taken (unlikely), use UUID-based
    short_uuid = str(uuid.uuid4()).replace('-', '')[:4]
    return short_uuid


def load_pin_mapping() -> dict:
    """Load PIN mapping from JSON file"""
    try:
        with open(PIN_MAPPING_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        return {}


def save_pin_mapping(mapping: dict):
    """Save PIN mapping to JSON file"""
    with open(PIN_MAPPING_FILE, 'w') as f:
        json.dump(mapping, f, indent=2)


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


def generate_qr_code_image(url: str, size: int = 10, border: int = 4, pin: str = None) -> bytes:
    """Generate QR code image as PNG bytes with optional PIN text below"""
    from PIL import Image, ImageDraw, ImageFont
    
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=size,
        border=border,
    )
    qr.add_data(url)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Add PIN text below QR code if provided
    if pin:
        # Calculate dimensions
        qr_width, qr_height = img.size
        text_height = 60  # Space for text
        padding = 20
        
        # Create new image with space for text
        new_img = Image.new('RGB', (qr_width, qr_height + text_height + padding), 'white')
        new_img.paste(img, (0, 0))
        
        # Draw text
        draw = ImageDraw.Draw(new_img)
        
        # Try to use a nice font, fallback to default if not available
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 32)
        except:
            try:
                font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 32)
            except:
                font = ImageFont.load_default()
        
        # Center the text
        text = f"Table PIN: {pin}"
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_x = (qr_width - text_width) // 2
        text_y = qr_height + padding
        
        # Draw text
        draw.text((text_x, text_y), text, fill='black', font=font)
        
        img = new_img
    
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


@app.get("/api/qr-menu/table/pin/{pin}")
async def get_table_number_from_pin(pin: str):
    """Get table number from PIN"""
    pin_mapping = load_pin_mapping()
    table_number = pin_mapping.get(pin)
    
    if table_number is None:
        raise HTTPException(status_code=404, detail="Invalid PIN")
    
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


@app.get("/api/qr-menu/orders/ready", response_model=List[ReadyOrderItem])
async def get_ready_orders():
    """
    Get ready orders for robot delivery system.
    
    Returns a list of ready orders with table number and order_id.
    Robot uses order_id to mark orders as delivered or failed.
    
    **Example Response:**
    ```json
    [
        {
            "table_number": "Table_1",
            "order_id": "abc123-def456-ghi789"
        },
        {
            "table_number": "Table_4",
            "order_id": "xyz789-uvw456-rst123"
        }
    ]
    ```
    
    Returns empty array `[]` if no ready orders exist.
    """
    orders = load_orders()
    
    # Filter orders with status="ready"
    ready_orders = [o for o in orders if o.get("status") == "ready"]
    
    if not ready_orders:
        return []
    
    # Format as JSON with table_number and order_id
    result = [
        ReadyOrderItem(
            table_number=f"Table_{o.get('table_number')}",
            order_id=o.get("order_id")
        )
        for o in ready_orders
    ]
    
    return result


@app.patch("/api/qr-menu/orders/{order_id}")
async def update_order_status(order_id: str, update: OrderUpdate):
    """
    Update order status.
    
    Used by robot to mark orders as delivered or failed.
    
    Request body example:
    {
        "status": "delivered"
    }
    
    or
    
    {
        "status": "failed"
    }
    
    Valid statuses: "pending", "ready", "delivered", "failed"
    
    Returns the updated order object.
    """
    orders = load_orders()
    
    # Validate status
    valid_statuses = ["pending", "ready", "delivered", "failed"]
    if update.status not in valid_statuses:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
        )
    
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
    """Configure total number of tables - auto-generates tokens, PINs and mappings (admin only)"""
    if config.total_tables < 1:
        raise HTTPException(status_code=400, detail="Total tables must be at least 1")
    
    if config.total_tables > 100:
        raise HTTPException(status_code=400, detail="Total tables cannot exceed 100")
    
    # Generate new mappings
    new_mapping = {}
    new_pin_mapping = {}
    existing_pins = set()
    
    for table_num in range(1, config.total_tables + 1):
        token = generate_table_token(table_num)
        pin = generate_table_pin(existing_pins)
        existing_pins.add(pin)
        new_mapping[token] = table_num
        new_pin_mapping[pin] = table_num
    
    # Save the new mappings (replaces all existing)
    save_table_mapping(new_mapping)
    save_pin_mapping(new_pin_mapping)
    
    # Convert to list format for response
    tables = []
    for token, table_num in new_mapping.items():
        pin = next((p for p, tn in new_pin_mapping.items() if tn == table_num), None)
        tables.append({"token": token, "table_number": table_num, "pin": pin})
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
    pin_mapping = load_pin_mapping()
    
    # Find token for this table number
    token = next((t for t, tn in mapping.items() if tn == table_number), None)
    if token is None:
        raise HTTPException(status_code=404, detail=f"Table {table_number} not found")
    
    # Find PIN for this table number
    pin = next((p for p, tn in pin_mapping.items() if tn == table_number), None)
    
    # Generate QR code URL
    qr_url = f"{get_frontend_url()}?t={token}"
    
    # Generate QR code image with PIN
    qr_image = generate_qr_code_image(qr_url, pin=pin)
    
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
    pin_mapping = load_pin_mapping()
    
    if not mapping:
        raise HTTPException(status_code=404, detail="No tables configured. Please configure tables first.")
    
    # Create ZIP file in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for token, table_number in mapping.items():
            # Find PIN for this table number
            pin = next((p for p, tn in pin_mapping.items() if tn == table_number), None)
            
            # Generate QR code URL
            qr_url = f"{get_frontend_url()}?t={token}"
            
            # Generate QR code image with PIN
            qr_image = generate_qr_code_image(qr_url, pin=pin)
            
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
    pin_mapping = load_pin_mapping()
    
    tables_info = []
    frontend_url = get_frontend_url()
    for token, table_number in sorted(mapping.items(), key=lambda x: x[1]):
        # Find PIN for this table number
        pin = next((p for p, tn in pin_mapping.items() if tn == table_number), None)
        qr_url = f"{frontend_url}?t={token}"
        tables_info.append({
            "table_number": table_number,
            "token": token,
            "pin": pin,
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


# Robot Logs Dashboard API Endpoints
def load_robot_data():
    """Load robot data from JSON file"""
    try:
        if not ROBOT_DATA_LOG_FILE.exists():
            return None
        with open(ROBOT_DATA_LOG_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading robot data: {e}")
        return None


def parse_timestamp(timestamp_str):
    """Parse timestamp string to datetime object"""
    try:
        return datetime.strptime(timestamp_str, "%Y-%m-%d %I:%M:%S %p")
    except:
        try:
            return datetime.strptime(timestamp_str.split('.')[0], "%Y-%m-%d %H:%M:%S")
        except:
            return None


def calculate_hourly_orders(data, hours=24):
    """Calculate orders per hour for the last N hours"""
    missions = data.get("all_missions", [])
    hourly_counts = defaultdict(int)
    
    # Get current time and calculate time range
    now = datetime.now()
    cutoff_time = now - timedelta(hours=hours)
    
    for mission in missions:
        if not mission.get("is_delivery", False):
            continue
        
        start_time_str = mission.get("start_time", "")
        if not start_time_str:
            continue
        
        mission_time = parse_timestamp(start_time_str)
        if mission_time and mission_time >= cutoff_time:
            hour = mission_time.hour
            hourly_counts[hour] += 1
    
    # Fill in all hours with 0 if no data
    result = []
    for i in range(24):
        result.append({
            "hour": i,
            "orders": hourly_counts.get(i, 0)
        })
    
    return result


def calculate_daily_trips(data, days=7):
    """Calculate trips per day for the last N days"""
    missions = data.get("all_missions", [])
    daily_counts = defaultdict(int)
    
    # Get current date and calculate date range
    now = datetime.now()
    
    for mission in missions:
        start_time_str = mission.get("start_time", "")
        if not start_time_str:
            continue
        
        mission_time = parse_timestamp(start_time_str)
        if mission_time:
            date_key = mission_time.strftime("%Y-%m-%d")
            # Only include missions from the last N days
            if (now - mission_time).days <= days:
                daily_counts[date_key] += 1
    
    # Get last N days and format
    result = []
    for i in range(days - 1, -1, -1):
        date = now - timedelta(days=i)
        date_key = date.strftime("%Y-%m-%d")
        date_str = date.strftime("%b %d")
        result.append({
            "date": date_str,
            "trips": daily_counts.get(date_key, 0)
        })
    
    return result


def calculate_metrics(data):
    """Calculate all dashboard metrics from robot data"""
    if not data:
        return None
    
    missions = data.get("all_missions", [])
    sessions = data.get("sessions", [])
    
    # Filter unique missions
    unique_missions = {}
    for mission in missions:
        mission_id = mission.get("mission_id")
        if mission_id and mission_id not in unique_missions:
            unique_missions[mission_id] = mission
    
    missions_list = list(unique_missions.values())
    
    # Calculate basic stats
    total_missions = len(missions_list)
    completed_missions = sum(1 for m in missions_list if m.get("status") == "COMPLETED")
    failed_missions = sum(1 for m in missions_list if m.get("status") == "FAILED")
    total_deliveries = sum(1 for m in missions_list if m.get("is_delivery", False))
    
    total_distance = sum(m.get("total_distance_m", 0) for m in missions_list)
    total_moving_time = sum(m.get("moving_time_sec", 0) for m in missions_list)
    total_idle_time = sum(m.get("idle_time_sec", 0) for m in missions_list)
    
    # Calculate runtime from sessions
    if sessions:
        total_runtime = sum(s.get("session_duration_sec", 0) for s in sessions)
    else:
        total_runtime = total_moving_time + total_idle_time
    
    # Calculate metrics
    success_rate = (completed_missions / total_missions * 100) if total_missions > 0 else 0
    robot_utilization = (total_moving_time / total_runtime * 100) if total_runtime > 0 else 0
    orders_per_hour = (total_deliveries / total_runtime * 3600) if total_runtime > 0 else 0
    avg_speed = (total_distance / total_moving_time) if total_moving_time > 0 else 0
    
    # Calculate peak busy hour
    hourly_orders = calculate_hourly_orders(data, 24)
    peak_hour_data = max(hourly_orders, key=lambda x: x["orders"])
    peak_busy_hour = peak_hour_data["hour"]
    
    # Calculate trips per day (today)
    daily_trips = calculate_daily_trips(data, 7)
    trips_per_day = daily_trips[-1]["trips"] if daily_trips else 0
    
    return {
        "ordersPerHour": round(orders_per_hour, 1),
        "tripsPerDay": trips_per_day,
        "robotUtilization": round(robot_utilization, 1),
        "successRate": round(success_rate, 1),
        "distanceCovered": round(total_distance / 1000, 2),  # Convert to km
        "avgRobotSpeed": round(avg_speed, 2),
        "peakBusyHour": peak_busy_hour,
    }


def get_error_logs(data):
    """Extract error and fault logs from robot data"""
    if not data:
        return []
    
    error_logs = []
    
    # Brake events
    brake_events = data.get("brake_events", [])
    brake_engaged_count = sum(1 for e in brake_events if e.get("engaged"))
    brake_disengaged_count = sum(1 for e in brake_events if not e.get("engaged"))
    
    if brake_engaged_count > 0:
        latest_brake = max([e for e in brake_events if e.get("engaged")], 
                          key=lambda x: x.get("timestamp", ""), default=None)
        error_logs.append({
            "type": "Break Engage & Disengaged",
            "severity": "medium",
            "count": brake_engaged_count + brake_disengaged_count,
            "timestamp": latest_brake.get("timestamp", "") if latest_brake else datetime.now().isoformat()
        })
    
    # Emergency events
    emergency_events = data.get("emergency_events", [])
    emergency_pressed = sum(1 for e in emergency_events if e.get("active"))
    
    if emergency_pressed > 0:
        latest_emergency = max([e for e in emergency_events if e.get("active")], 
                              key=lambda x: x.get("timestamp", ""), default=None)
        error_logs.append({
            "type": "Emergency Break Occurrence",
            "severity": "high",
            "count": emergency_pressed,
            "timestamp": latest_emergency.get("timestamp", "") if latest_emergency else datetime.now().isoformat()
        })
    
    # Mission failures
    missions = data.get("all_missions", [])
    failed_missions = [m for m in missions if m.get("status") == "FAILED"]
    
    if failed_missions:
        latest_failed = max(failed_missions, key=lambda x: x.get("start_time", ""), default=None)
        error_logs.append({
            "type": "Mission Fail",
            "severity": "high",
            "count": len(failed_missions),
            "timestamp": latest_failed.get("start_time", "") if latest_failed else datetime.now().isoformat()
        })
    
    # Goal failures (missions that failed to reach goal)
    goal_failures = [m for m in missions if m.get("status") == "FAILED" and "goal" in str(m.get("status", "")).lower()]
    if goal_failures:
        latest_goal_fail = max(goal_failures, key=lambda x: x.get("start_time", ""), default=None)
        error_logs.append({
            "type": "Goal Fail",
            "severity": "high",
            "count": len(goal_failures),
            "timestamp": latest_goal_fail.get("start_time", "") if latest_goal_fail else datetime.now().isoformat()
        })
    
    # Battery low events
    battery_samples = data.get("battery_samples", [])
    low_battery_events = [s for s in battery_samples if "event" in s or s.get("voltage", 0) < 20]
    
    if low_battery_events:
        latest_battery = max(low_battery_events, key=lambda x: x.get("timestamp", ""), default=None)
        error_logs.append({
            "type": "Battery Hit 20% Threshold",
            "severity": "medium",
            "count": len(low_battery_events),
            "timestamp": latest_battery.get("timestamp", "") if latest_battery else datetime.now().isoformat()
        })
    
    # Navigation timeout (missions with very long duration might indicate timeout)
    long_duration_missions = [m for m in missions if m.get("total_duration_sec", 0) > 1800]  # > 30 minutes
    if long_duration_missions:
        latest_timeout = max(long_duration_missions, key=lambda x: x.get("start_time", ""), default=None)
        error_logs.append({
            "type": "Navigation Timeout",
            "severity": "low",
            "count": len(long_duration_missions),
            "timestamp": latest_timeout.get("start_time", "") if latest_timeout else datetime.now().isoformat()
        })
    
    # Sensor errors (placeholder - would need actual sensor error data)
    # This is a placeholder that can be expanded when sensor error data is available
    
    return error_logs


@app.get("/api/qr-menu/admin/robot-logs/metrics")
async def get_robot_logs_metrics():
    """
    Get all robot logs dashboard metrics (admin only)
    
    Returns:
    - ordersPerHour: Average orders per hour
    - tripsPerDay: Trips completed today
    - robotUtilization: Percentage of time robot is moving
    - successRate: Percentage of successful missions
    - distanceCovered: Total distance in km
    - avgRobotSpeed: Average speed in m/s
    - peakBusyHour: Hour with most activity (0-23)
    """
    data = load_robot_data()
    if not data:
        raise HTTPException(status_code=404, detail="Robot data log file not found")
    
    metrics = calculate_metrics(data)
    if not metrics:
        raise HTTPException(status_code=500, detail="Failed to calculate metrics")
    
    return metrics


@app.get("/api/qr-menu/admin/robot-logs/hourly-orders")
async def get_hourly_orders():
    """
    Get hourly orders data for the last 24 hours (admin only)
    
    Returns array of {hour: 0-23, orders: count}
    """
    data = load_robot_data()
    if not data:
        raise HTTPException(status_code=404, detail="Robot data log file not found")
    
    hourly_orders = calculate_hourly_orders(data, 24)
    return hourly_orders


@app.get("/api/qr-menu/admin/robot-logs/daily-trips")
async def get_daily_trips():
    """
    Get daily trips data for the last 7 days (admin only)
    
    Returns array of {date: "MMM DD", trips: count}
    """
    data = load_robot_data()
    if not data:
        raise HTTPException(status_code=404, detail="Robot data log file not found")
    
    daily_trips = calculate_daily_trips(data, 7)
    return daily_trips


@app.get("/api/qr-menu/admin/robot-logs/errors")
async def get_robot_logs_errors():
    """
    Get error and fault logs (admin only)
    
    Returns array of error objects with:
    - type: Error type description
    - severity: "high", "medium", or "low"
    - count: Number of occurrences
    - timestamp: ISO timestamp of last occurrence
    """
    data = load_robot_data()
    if not data:
        raise HTTPException(status_code=404, detail="Robot data log file not found")
    
    error_logs = get_error_logs(data)
    return error_logs


@app.get("/api/qr-menu/admin/robot-logs/dashboard")
async def get_robot_logs_dashboard():
    """
    Get complete robot logs dashboard data (admin only)
    
    Returns all metrics, hourly orders, daily trips, and error logs in one response
    """
    data = load_robot_data()
    if not data:
        raise HTTPException(status_code=404, detail="Robot data log file not found")
    
    metrics = calculate_metrics(data)
    hourly_orders = calculate_hourly_orders(data, 24)
    daily_trips = calculate_daily_trips(data, 7)
    error_logs = get_error_logs(data)
    
    if not metrics:
        raise HTTPException(status_code=500, detail="Failed to calculate metrics")
    
    return {
        **metrics,
        "hourlyOrders": hourly_orders,
        "dailyTrips": daily_trips,
        "errorLogs": error_logs
    }


