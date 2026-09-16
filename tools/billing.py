from decimal import Decimal, ROUND_HALF_UP

from db.database import get_conn, immediate_transaction
from tools.errors import ToolError
from tools.inventory import find_product
from tools.khata import _credit_internal


def _r2(x):
    """Round to 2 decimal places the way an invoice does (half-up), not
    Python's default banker's rounding."""
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def start_bill(chat_id, customer_name=None, payment_mode=None):
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO bills(status, customer_name, payment_mode, chat_id) VALUES ('draft', ?, ?, ?)",
            (customer_name, payment_mode, chat_id),
        )
        bill_id = cur.lastrowid
        conn.execute(
            "INSERT INTO chat_sessions(chat_id, draft_bill_id) VALUES (?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET draft_bill_id = excluded.draft_bill_id, updated_at = datetime('now')",
            (chat_id, bill_id),
        )
        conn.commit()
    finally:
        conn.close()
    return {"bill_id": bill_id, "status": "draft"}


def get_draft_bill_id(chat_id):
    conn = get_conn()
    try:
        row = conn.execute("SELECT draft_bill_id FROM chat_sessions WHERE chat_id = ?", (chat_id,)).fetchone()
        return row["draft_bill_id"] if row else None
    finally:
        conn.close()


def _line_amounts(qty, unit_price, gst_rate):
    taxable = _r2(qty * unit_price)
    cgst = _r2(taxable * (gst_rate / 2) / 100)
    sgst = _r2(taxable * (gst_rate / 2) / 100)
    line_total = _r2(taxable + cgst + sgst)
    return taxable, cgst, sgst, line_total


def add_bill_item(bill_id, product_query, qty, unit_override=None):
    if qty is None or qty <= 0:
        raise ToolError("Quantity must be positive.")
    matches = find_product(product_query)
    if not matches:
        raise ToolError(f"No product matching '{product_query}'. Check spelling, or it may need adding first.")
    if len(matches) > 1:
        names = ", ".join(f"{m['name']} ({m['brand'] or 'generic'})" for m in matches)
        raise ToolError(f"'{product_query}' is ambiguous: {names}. Ask which one before billing it.")
    p = matches[0]

    conn = get_conn()
    try:
        bill = conn.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
        if not bill:
            raise ToolError(f"No bill #{bill_id}.")
        if bill["status"] != "draft":
            raise ToolError(f"Bill #{bill_id} is already {bill['status']}; can't add items to it.")

        taxable, cgst, sgst, line_total = _line_amounts(qty, p["sell_price"], p["gst_rate"])
        cur = conn.execute(
            """INSERT INTO bill_items
               (bill_id, product_id, product_name, qty, unit, unit_price, gst_rate,
                taxable_value, cgst_amt, sgst_amt, line_total, hsn_code)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                bill_id, p["id"], p["name"], qty, unit_override or p["unit"], p["sell_price"], p["gst_rate"],
                taxable, cgst, sgst, line_total, p["hsn_code"],
            ),
        )
        item_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    return {
        "item_id": item_id, "product": p["name"], "qty": qty, "unit_price": p["sell_price"],
        "line_total": line_total, **_totals(bill_id),
    }


def remove_bill_item(bill_id, item_id=None, product_query=None):
    conn = get_conn()
    try:
        bill = conn.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
        if not bill or bill["status"] != "draft":
            raise ToolError(f"Bill #{bill_id} isn't an editable draft.")
        row = None
        if item_id:
            row = conn.execute(
                "SELECT * FROM bill_items WHERE id = ? AND bill_id = ?", (item_id, bill_id)
            ).fetchone()
        elif product_query:
            row = conn.execute(
                "SELECT * FROM bill_items WHERE bill_id = ? AND product_name LIKE ? ORDER BY id DESC LIMIT 1",
                (bill_id, f"%{product_query}%"),
            ).fetchone()
        if not row:
            raise ToolError("No matching line item on this bill.")
        conn.execute("DELETE FROM bill_items WHERE id = ?", (row["id"],))
        conn.commit()
        removed_name = row["product_name"]
    finally:
        conn.close()
    return {"removed": removed_name, **_totals(bill_id)}


def update_bill_item_qty(bill_id, item_id, new_qty):
    if new_qty is None or new_qty <= 0:
        raise ToolError("Quantity must be positive; use remove_bill_item to drop a line entirely.")
    conn = get_conn()
    try:
        item = conn.execute("SELECT * FROM bill_items WHERE id = ? AND bill_id = ?", (item_id, bill_id)).fetchone()
        if not item:
            raise ToolError("No such line item on this bill.")
        taxable, cgst, sgst, line_total = _line_amounts(new_qty, item["unit_price"], item["gst_rate"])
        conn.execute(
            "UPDATE bill_items SET qty=?, taxable_value=?, cgst_amt=?, sgst_amt=?, line_total=? WHERE id=?",
            (new_qty, taxable, cgst, sgst, line_total, item_id),
        )
        conn.commit()
    finally:
        conn.close()
    return _totals(bill_id)


def _totals(bill_id):
    conn = get_conn()
    try:
        items = conn.execute("SELECT * FROM bill_items WHERE bill_id = ?", (bill_id,)).fetchall()
    finally:
        conn.close()
    subtotal = _r2(sum(i["taxable_value"] for i in items))
    cgst = _r2(sum(i["cgst_amt"] for i in items))
    sgst = _r2(sum(i["sgst_amt"] for i in items))
    total = _r2(subtotal + cgst + sgst)
    return {
        "items": [
            {"item_id": i["id"], "product": i["product_name"], "qty": i["qty"], "unit": i["unit"],
             "line_total": i["line_total"]} for i in items
        ],
        "subtotal": subtotal, "cgst_total": cgst, "sgst_total": sgst, "total": total,
    }


def get_bill(bill_id):
    conn = get_conn()
    try:
        bill = conn.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
        if not bill:
            raise ToolError(f"No bill #{bill_id}.")
        items = conn.execute("SELECT * FROM bill_items WHERE bill_id = ?", (bill_id,)).fetchall()
    finally:
        conn.close()
    return {"bill": dict(bill), "items": [dict(i) for i in items]}


def finalize_bill(bill_id, payment_mode, payment_ref=None, idempotency_key=None):
    """
    The only place stock actually leaves the shelf. Runs inside a single
    BEGIN IMMEDIATE transaction, so it can't interleave with a concurrent sale
    or stock-in on the same product. The oversell guard is a conditional
    UPDATE (qty_on_hand >= qty), not a read-then-write — so there's no window
    for a race to slip through. idempotency_key is injected by the dispatcher
    from (chat_id, telegram update_id), not supplied by the model, so a
    redelivered Telegram update — or the model retrying the tool call — can
    never double-bill or double-decrement stock.
    """
    if payment_mode not in ("cash", "upi", "card", "credit"):
        raise ToolError("payment_mode must be one of cash, upi, card, credit.")
    if not idempotency_key:
        raise ToolError("Internal error: finalize_bill requires an idempotency_key.")

    with immediate_transaction() as conn:
        existing = conn.execute("SELECT * FROM bills WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
        if existing:
            items = conn.execute("SELECT * FROM bill_items WHERE bill_id = ?", (existing["id"],)).fetchall()
            return {
                "bill_id": existing["id"], "status": existing["status"], "total": existing["total"],
                "already_processed": True, "items": [dict(i) for i in items],
            }

        bill = conn.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
        if not bill:
            raise ToolError(f"No bill #{bill_id}.")
        if bill["status"] == "finalized":
            items = conn.execute("SELECT * FROM bill_items WHERE bill_id = ?", (bill_id,)).fetchall()
            return {
                "bill_id": bill_id, "status": "finalized", "total": bill["total"],
                "already_processed": True, "items": [dict(i) for i in items],
            }
        if bill["status"] != "draft":
            raise ToolError(f"Bill #{bill_id} is {bill['status']}, can't finalize.")

        items = conn.execute("SELECT * FROM bill_items WHERE bill_id = ?", (bill_id,)).fetchall()
        if not items:
            raise ToolError("Bill has no items to finalize.")

        customer_name = bill["customer_name"]
        if payment_mode == "credit" and not customer_name:
            raise ToolError("A credit sale needs a customer name on the bill — who is this khata for?")

        # Oversell guard: atomic, conditional, all-or-nothing across every line.
        for it in items:
            cur = conn.execute(
                "UPDATE products SET qty_on_hand = qty_on_hand - ?, updated_at = datetime('now') "
                "WHERE id = ? AND qty_on_hand >= ?",
                (it["qty"], it["product_id"], it["qty"]),
            )
            if cur.rowcount == 0:
                stock = conn.execute(
                    "SELECT qty_on_hand, unit FROM products WHERE id = ?", (it["product_id"],)
                ).fetchone()
                raise ToolError(
                    f"Cannot finalize: only {stock['qty_on_hand']}{stock['unit']} of "
                    f"{it['product_name']} in stock, this bill wants {it['qty']}{it['unit']}. "
                    f"Reduce the quantity or drop the item before finalizing."
                )
            conn.execute(
                "INSERT INTO stock_movements(product_id, change_qty, movement_type, ref_type, ref_id) "
                "VALUES (?,?,?,?,?)",
                (it["product_id"], -it["qty"], "out", "bill", bill_id),
            )

        subtotal = _r2(sum(i["taxable_value"] for i in items))
        cgst = _r2(sum(i["cgst_amt"] for i in items))
        sgst = _r2(sum(i["sgst_amt"] for i in items))
        raw_total = subtotal + cgst + sgst
        total = round(raw_total)  # round off to the nearest rupee on the invoice, standard practice
        round_off = _r2(total - raw_total)

        try:
            conn.execute(
                "UPDATE bills SET status='finalized', payment_mode=?, payment_ref=?, subtotal=?, "
                "cgst_total=?, sgst_total=?, round_off=?, total=?, idempotency_key=?, finalized_at=datetime('now') "
                "WHERE id = ?",
                (payment_mode, payment_ref, subtotal, cgst, sgst, round_off, total, idempotency_key, bill_id),
            )
        except Exception as e:
            if "UNIQUE" in str(e):
                # Raced with another finalize using the same key between our check and this write.
                existing = conn.execute("SELECT * FROM bills WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
                return {"bill_id": existing["id"], "status": existing["status"], "total": existing["total"], "already_processed": True}
            raise

        if payment_mode == "credit":
            _credit_internal(conn, customer_name, total, ref_bill_id=bill_id, note=f"Bill #{bill_id}")

    return {
        "bill_id": bill_id, "status": "finalized", "subtotal": subtotal, "cgst_total": cgst,
        "sgst_total": sgst, "round_off": round_off, "total": total, "already_processed": False,
    }
