TOOLS_SCHEMA = [
    {
        "name": "find_product",
        "description": "Look up products by name or brand (fuzzy substring match). Use this to check "
                        "whether a product exists and to resolve ambiguity before billing or receiving stock.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Product name or brand to search for"}},
            "required": ["query"],
        },
    },
    {
        "name": "add_product",
        "description": "Add a brand-new SKU to the catalog with its GST slab, HSN code, prices and unit. "
                        "Use for 'new item: ...' requests. Do not use this to top up stock of an existing "
                        "product — use receive_stock for that.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "brand": {"type": "string", "description": "Omit for loose/generic items like sugar or rice"},
                "category": {"type": "string"},
                "unit": {"type": "string", "enum": ["kg", "g", "l", "ml", "packet", "dozen", "piece"]},
                "is_loose": {"type": "boolean", "description": "true for loose items sold by weight (sugar, rice, dal)"},
                "hsn_code": {"type": "string"},
                "gst_rate": {"type": "number", "description": "Full GST slab percent, e.g. 0, 5, 12, 18"},
                "cost_price": {"type": "number"},
                "mrp": {"type": "number"},
                "sell_price": {"type": "number", "description": "Defaults to MRP if omitted"},
                "reorder_level": {"type": "number", "description": "Stock level at which to flag for reorder"},
                "initial_qty": {"type": "number", "description": "Opening stock quantity, if any"},
            },
            "required": ["name", "unit", "gst_rate", "cost_price", "mrp"],
        },
    },
    {
        "name": "receive_stock",
        "description": "Record incoming stock for an existing product (a delivery/purchase). Increments "
                        "qty_on_hand and optionally updates cost/MRP/sell price if they changed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_query": {"type": "string"},
                "qty": {"type": "number"},
                "cost_price": {"type": "number"},
                "mrp": {"type": "number"},
                "sell_price": {"type": "number"},
                "note": {"type": "string"},
            },
            "required": ["product_query", "qty"],
        },
    },
    {
        "name": "get_stock_level",
        "description": "Check current stock quantity for a product, e.g. 'how much sugar is left?'.",
        "input_schema": {
            "type": "object",
            "properties": {"product_query": {"type": "string"}},
            "required": ["product_query"],
        },
    },
    {
        "name": "list_low_stock",
        "description": "List every product at or below its reorder level — for 'what's running out?'.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_products",
        "description": "List the full catalog, optionally filtered by category.",
        "input_schema": {"type": "object", "properties": {"category": {"type": "string"}}},
    },
    {
        "name": "start_bill",
        "description": "Start a new draft bill for this chat. Call this when the owner begins cutting a "
                        "bill. Any existing draft bill for this chat is replaced.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_name": {"type": "string", "description": "Only needed for credit/khata sales"},
                "payment_mode": {"type": "string", "enum": ["cash", "upi", "card", "credit"]},
            },
        },
    },
    {
        "name": "add_bill_item",
        "description": "Add one line item to the current draft bill. Price and GST are looked up from the "
                        "catalog automatically — never state a price yourself. Omit bill_id to use the "
                        "chat's current open draft.",
        "input_schema": {
            "type": "object",
            "properties": {
                "bill_id": {"type": "integer"},
                "product_query": {"type": "string"},
                "qty": {"type": "number"},
                "unit_override": {"type": "string", "description": "Only if the owner explicitly overrides the catalog unit"},
            },
            "required": ["product_query", "qty"],
        },
    },
    {
        "name": "remove_bill_item",
        "description": "Drop a line item from the current draft bill, by item_id or by product name "
                        "('drop the butter').",
        "input_schema": {
            "type": "object",
            "properties": {
                "bill_id": {"type": "integer"},
                "item_id": {"type": "integer"},
                "product_query": {"type": "string"},
            },
        },
    },
    {
        "name": "update_bill_item_qty",
        "description": "Change the quantity of an existing line item on the draft bill ('make it 6 Maggi').",
        "input_schema": {
            "type": "object",
            "properties": {
                "bill_id": {"type": "integer"},
                "item_id": {"type": "integer"},
                "new_qty": {"type": "number"},
            },
            "required": ["item_id", "new_qty"],
        },
    },
    {
        "name": "get_bill",
        "description": "Fetch full details of a bill (draft or finalized) by id.",
        "input_schema": {
            "type": "object",
            "properties": {"bill_id": {"type": "integer"}},
            "required": ["bill_id"],
        },
    },
    {
        "name": "finalize_bill",
        "description": "Finalize the draft bill: decrements stock (refusing if any line would oversell), "
                        "computes GST totals, and records the sale. This is irreversible — only call it once "
                        "the owner has clearly confirmed the sale (e.g. stated a payment mode). Omit bill_id "
                        "to use the chat's current open draft.",
        "input_schema": {
            "type": "object",
            "properties": {
                "bill_id": {"type": "integer"},
                "payment_mode": {"type": "string", "enum": ["cash", "upi", "card", "credit"]},
                "payment_ref": {"type": "string", "description": "UPI/card reference, if given"},
            },
            "required": ["payment_mode"],
        },
    },
    {
        "name": "add_khata_credit",
        "description": "Put an amount on a customer's credit (khata) directly, not tied to a bill "
                        "('put ₹500 on Ramesh's credit').",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_name": {"type": "string"},
                "amount": {"type": "number"},
                "note": {"type": "string"},
            },
            "required": ["customer_name", "amount"],
        },
    },
    {
        "name": "add_khata_payment",
        "description": "Record a customer settling (part of) their khata balance ('Ramesh paid ₹300').",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_name": {"type": "string"},
                "amount": {"type": "number"},
                "note": {"type": "string"},
            },
            "required": ["customer_name", "amount"],
        },
    },
    {
        "name": "get_khata_balance",
        "description": "Look up a customer's current khata balance and recent transactions.",
        "input_schema": {
            "type": "object",
            "properties": {"customer_name": {"type": "string"}},
            "required": ["customer_name"],
        },
    },
    {
        "name": "list_khata_customers",
        "description": "List customers with outstanding khata balances (or all customers).",
        "input_schema": {
            "type": "object",
            "properties": {"only_outstanding": {"type": "boolean"}},
        },
    },
    {
        "name": "get_daily_close",
        "description": "Get today's (or a given date's) sales total, tax collected, payment-mode split and "
                        "top items — for 'close the day' / 'today's sales?'.",
        "input_schema": {
            "type": "object",
            "properties": {"for_date": {"type": "string", "description": "YYYY-MM-DD, defaults to today"}},
        },
    },
    {
        "name": "get_sales_summary",
        "description": "Get aggregated sales figures over a date range, for reporting or before building an "
                        "analysis deck.",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "YYYY-MM-DD"},
            },
            "required": ["start_date", "end_date"],
        },
    },
    {
        "name": "generate_invoice_pdf",
        "description": "Generate a GST-correct PDF invoice for a finalized bill. The file is attached "
                        "automatically after your reply — just confirm you're sending it.",
        "input_schema": {
            "type": "object",
            "properties": {"bill_id": {"type": "integer"}},
            "required": ["bill_id"],
        },
    },
    {
        "name": "generate_analysis_deck",
        "description": "Generate a PowerPoint sales analysis deck (KPIs, charts, reorder list) for a date "
                        "range. The file is attached automatically after your reply.",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "YYYY-MM-DD"},
            },
            "required": ["start_date", "end_date"],
        },
    },
    {
        "name": "get_preference",
        "description": "Read a single standing owner preference by key.",
        "input_schema": {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
    },
    {
        "name": "set_preference",
        "description": "Save a standing owner preference so it persists across chats and restarts — e.g. "
                        "default payment mode, preferred brand for an item, shop name/GSTIN/address for "
                        "invoices. Call this whenever the owner states a standing rule, don't just acknowledge "
                        "it in words.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "e.g. default_payment_mode, default_atta, shop_name, shop_gstin, shop_address"},
                "value": {"type": "string"},
            },
            "required": ["key", "value"],
        },
    },
    {
        "name": "list_preferences",
        "description": "List all standing owner preferences currently saved.",
        "input_schema": {"type": "object", "properties": {}},
    },
]
