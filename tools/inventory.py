from db.database import get_conn, immediate_transaction
from tools.errors import ToolError

VALID_UNITS = {"kg", "g", "l", "ml", "packet", "dozen", "piece"}


def find_product(query: str):
    """Loose name/brand lookup. Returns every match so the caller (agent or
    another tool) can decide whether it's unambiguous."""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM products WHERE name LIKE ? OR brand LIKE ? ORDER BY name",
            (f"%{query}%", f"%{query}%"),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def add_product(
    name,
    unit,
    gst_rate,
    cost_price,
    mrp,
    sell_price=None,
    brand=None,
    category=None,
    is_loose=False,
    hsn_code=None,
    reorder_level=0,
    initial_qty=0,
):
    if unit not in VALID_UNITS:
        raise ToolError(f"Unknown unit '{unit}'. Must be one of {sorted(VALID_UNITS)}.")
    if sell_price is None:
        sell_price = mrp
    if cost_price < 0 or mrp < 0 or sell_price < 0:
        raise ToolError("Prices cannot be negative.")
    if sell_price < cost_price:
        raise ToolError(
            f"Sell price (₹{sell_price}) is below cost price (₹{cost_price}) for {name}. "
            f"Confirm this is intentional before adding it — otherwise every sale loses money."
        )

    with immediate_transaction() as conn:
        try:
            cur = conn.execute(
                """INSERT INTO products
                   (name, brand, category, unit, is_loose, hsn_code, gst_rate,
                    cost_price, mrp, sell_price, qty_on_hand, reorder_level)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    name, brand, category, unit, int(bool(is_loose)), hsn_code, gst_rate,
                    cost_price, mrp, sell_price, initial_qty, reorder_level,
                ),
            )
        except Exception as e:
            if "UNIQUE" in str(e):
                raise ToolError(f"Product '{name}' ({brand or 'no brand'}) already exists.")
            raise
        product_id = cur.lastrowid
        if initial_qty:
            conn.execute(
                "INSERT INTO stock_movements(product_id, change_qty, movement_type, ref_type, unit_cost) "
                "VALUES (?,?,?,?,?)",
                (product_id, initial_qty, "in", "initial_stock", cost_price),
            )

    return {"product_id": product_id, "name": name, "brand": brand, "unit": unit, "qty_on_hand": initial_qty}


def receive_stock(product_query, qty, cost_price=None, mrp=None, sell_price=None, note=None):
    if qty is None or qty <= 0:
        raise ToolError("Quantity received must be positive.")

    with immediate_transaction() as conn:
        matches = conn.execute(
            "SELECT * FROM products WHERE name LIKE ? OR brand LIKE ?",
            (f"%{product_query}%", f"%{product_query}%"),
        ).fetchall()
        if len(matches) == 0:
            raise ToolError(
                f"No product matching '{product_query}'. It needs to be added with add_product first "
                f"(ask the owner for GST rate, MRP, HSN if unknown)."
            )
        if len(matches) > 1:
            names = ", ".join(f"{m['name']} ({m['brand'] or 'generic'})" for m in matches)
            raise ToolError(f"'{product_query}' is ambiguous: {names}. Ask which one.")

        product = matches[0]
        sets = ["qty_on_hand = qty_on_hand + ?", "updated_at = datetime('now')"]
        params = [qty]
        if cost_price is not None:
            sets.append("cost_price = ?")
            params.append(cost_price)
        if mrp is not None:
            sets.append("mrp = ?")
            params.append(mrp)
        if sell_price is not None:
            sets.append("sell_price = ?")
            params.append(sell_price)
        params.append(product["id"])

        conn.execute(f"UPDATE products SET {', '.join(sets)} WHERE id = ?", params)
        conn.execute(
            "INSERT INTO stock_movements(product_id, change_qty, movement_type, ref_type, unit_cost, note) "
            "VALUES (?,?,?,?,?,?)",
            (product["id"], qty, "in", "purchase", cost_price if cost_price is not None else product["cost_price"], note),
        )
        new_qty = product["qty_on_hand"] + qty

    return {
        "product_id": product["id"],
        "name": product["name"],
        "brand": product["brand"],
        "received": qty,
        "new_qty_on_hand": new_qty,
    }


def get_stock_level(product_query):
    matches = find_product(product_query)
    if not matches:
        raise ToolError(f"No product matching '{product_query}'.")
    return [
        {
            "name": m["name"], "brand": m["brand"], "qty_on_hand": m["qty_on_hand"],
            "unit": m["unit"], "reorder_level": m["reorder_level"],
        }
        for m in matches
    ]


def list_low_stock():
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT name, brand, qty_on_hand, unit, reorder_level FROM products "
            "WHERE qty_on_hand <= reorder_level ORDER BY qty_on_hand ASC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_products(category=None):
    conn = get_conn()
    try:
        if category:
            rows = conn.execute(
                "SELECT * FROM products WHERE category LIKE ? ORDER BY name", (f"%{category}%",)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM products ORDER BY name").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
