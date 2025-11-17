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

**Note:** The QR code generation requires `qrcode` and `pillow` packages. These are included in `requirements.txt`.

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

### Admin - Table Configuration
- `GET /api/qr-menu/admin/tables` - Get all table mappings
  - Returns: `{"tables": [{"token": "...", "table_number": 1}, ...], "total": 5}`

- `POST /api/qr-menu/admin/tables/configure` - Configure total number of tables (auto-generates everything)
  - Body: `{"total_tables": 5}`
  - Returns: `{"message": "Successfully configured 5 table(s)", "total_tables": 5, "tables": [...]}`
  - **Auto-generates**: Table numbers (1 to N), unique tokens, and all mappings
  - **Replaces** all existing table configurations
  - Validates: Must be between 1 and 100 tables

### QR Code Generation (Admin)
- `GET /api/qr-menu/admin/qr-code/{table_number}` - Generate QR code for a specific table
  - Returns: PNG image file (downloadable)
  - Example: `GET /api/qr-menu/admin/qr-code/1` downloads `table_1_qr_code.png`
  - QR code contains URL: `{FRONTEND_URL}?t={token}`

- `GET /api/qr-menu/admin/qr-codes/all` - Generate QR codes for all tables
  - Returns: ZIP file containing all QR code images
  - Downloads: `all_table_qr_codes.zip` with files named `table_{number}_qr_code.png`
  - Perfect for bulk printing and placing on tables

- `GET /api/qr-menu/admin/qr-codes/info` - Get QR code URLs and info for all tables
  - Returns: `{"frontend_url": "...", "tables": [{"table_number": 1, "token": "...", "qr_url": "..."}, ...], "total": 5}`
  - Useful for getting URLs without downloading images

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

**Simple Configuration (Recommended)**
- Use `POST /api/qr-menu/admin/tables/configure` with just the total number of tables
- Example: `{"total_tables": 5}` will automatically:
  - Create tables numbered 1 through 5
  - Generate unique tokens for each table
  - Map everything automatically

**To generate and print QR codes:**
1. Configure tables: `POST /api/qr-menu/admin/tables/configure` with `{"total_tables": 5}`
2. Download all QR codes: `GET /api/qr-menu/admin/qr-codes/all` (downloads ZIP file)
3. Print the QR codes and place them on each table
4. Customers scan QR code → Opens menu with table token → Place order → Track by table number

**Frontend URL Configuration:**
- Default: `http://192.168.0.137:9111`
- Set custom URL via environment variable: `FRONTEND_URL=http://your-url:port`
- QR codes will contain: `{FRONTEND_URL}?t={table_token}`

**Manual Edit (Alternative)**
- You can also edit `table-mapping.json` directly if needed:
```json
{
  "table1_token_abc123": 1,
  "table2_token_def456": 2,
  "table3_token_ghi789": 3
}
```

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

