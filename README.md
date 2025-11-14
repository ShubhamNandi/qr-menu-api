# QR Menu API

FastAPI backend server for the QR Menu application. Handles table token mapping, order storage, and order management.

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

Or if using uv:
```bash
uv pip install -r requirements.txt
```

## Running the Server

Start the API server:
```bash
./start.sh
```

Or manually:
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

The API will be available at `http://192.168.0.137:8000` (or your machine's IP).

## API Endpoints

### Health Check
- `GET /` - API information
- `GET /api/qr-menu/health` - Health check

### Table Management
- `GET /api/qr-menu/table/{token}` - Get table number from token
  - Returns: `{"table_number": 5}`

### Orders
- `POST /api/qr-menu/orders` - Create new order
  - Body: `{"table_number": 5, "items": [...], "total": 2499, "timestamp": "...", "status": "pending"}`
  - Returns: `{"order_id": "...", "message": "Order saved successfully"}`

- `GET /api/qr-menu/orders` - Get all orders
  - Query params: `?table={number}`, `?status={pending/delivered}`
  - Returns: Array of orders

- `PATCH /api/qr-menu/orders/{order_id}` - Update order status
  - Body: `{"status": "delivered"}`
  - Returns: Updated order

## Configuration

### Table Mapping

Edit `table-mapping.json` to add new table tokens:

```json
{
  "table1_token_abc123": 1,
  "table2_token_def456": 2,
  "table3_token_ghi789": 3
}
```

To generate QR codes:
1. Create a unique token for each table
2. Add mapping in `table-mapping.json`
3. Generate QR code with URL: `http://192.168.0.137:9111?t=your_token_here`

### Order Storage

Orders are stored in `qr_menu_orders.json` (automatically created). This file is gitignored to avoid committing order data.

## CORS

The API is configured to allow requests from:
- `http://localhost:9111`
- `http://192.168.0.137:9111`
- `http://127.0.0.1:9111`

Update CORS origins in `main.py` if needed.

## API Documentation

FastAPI automatically generates interactive API documentation:
- Swagger UI: `http://192.168.0.137:8000/docs`
- ReDoc: `http://192.168.0.137:8000/redoc`

