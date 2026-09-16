from db.database import get_conn, immediate_transaction
from tools.errors import ToolError


def _get_or_create_customer(conn, name):
    row = conn.execute("SELECT * FROM khata_customers WHERE name = ?", (name,)).fetchone()
    if row:
        return row
    conn.execute("INSERT INTO khata_customers(name) VALUES (?)", (name,))
    return conn.execute("SELECT * FROM khata_customers WHERE name = ?", (name,)).fetchone()


def _credit_internal(conn, customer_name, amount, ref_bill_id=None, note=None, idempotency_key=None):
    """Used both by add_khata_credit and, within the same transaction, by
    finalize_bill when a sale is made on credit — so the stock decrement and
    the khata credit either both happen or neither does."""
    cust = _get_or_create_customer(conn, customer_name)
    conn.execute("UPDATE khata_customers SET balance = balance + ? WHERE id = ?", (amount, cust["id"]))
    conn.execute(
        "INSERT INTO khata_transactions(customer_id, type, amount, ref_bill_id, note, idempotency_key) "
        "VALUES (?,?,?,?,?,?)",
        (cust["id"], "credit", amount, ref_bill_id, note, idempotency_key),
    )


def add_khata_credit(customer_name, amount, note=None):
    if amount is None or amount <= 0:
        raise ToolError("Credit amount must be positive.")
    with immediate_transaction() as conn:
        _credit_internal(conn, customer_name, amount, note=note)
        bal = conn.execute(
            "SELECT balance FROM khata_customers WHERE name = ?", (customer_name,)
        ).fetchone()["balance"]
    return {"customer": customer_name, "credited": amount, "new_balance": bal}


def add_khata_payment(customer_name, amount, note=None):
    if amount is None or amount <= 0:
        raise ToolError("Payment amount must be positive.")
    with immediate_transaction() as conn:
        cust = conn.execute("SELECT * FROM khata_customers WHERE name = ?", (customer_name,)).fetchone()
        if not cust:
            raise ToolError(f"No khata found for '{customer_name}'. They have no credit on record.")
        if amount > cust["balance"] + 1e-6:
            raise ToolError(
                f"{customer_name} only owes ₹{cust['balance']:.2f}, can't record a payment of ₹{amount:.2f}. "
                f"Confirm the amount."
            )
        conn.execute("UPDATE khata_customers SET balance = balance - ? WHERE id = ?", (amount, cust["id"]))
        conn.execute(
            "INSERT INTO khata_transactions(customer_id, type, amount, note) VALUES (?,?,?,?)",
            (cust["id"], "payment", amount, note),
        )
        bal = conn.execute("SELECT balance FROM khata_customers WHERE id = ?", (cust["id"],)).fetchone()["balance"]
    return {"customer": customer_name, "paid": amount, "new_balance": bal}


def get_khata_balance(customer_name):
    conn = get_conn()
    try:
        cust = conn.execute("SELECT * FROM khata_customers WHERE name = ?", (customer_name,)).fetchone()
        if not cust:
            raise ToolError(f"No khata found for '{customer_name}'.")
        txns = conn.execute(
            "SELECT type, amount, note, created_at FROM khata_transactions "
            "WHERE customer_id = ? ORDER BY created_at DESC LIMIT 10",
            (cust["id"],),
        ).fetchall()
    finally:
        conn.close()
    return {"customer": customer_name, "balance": cust["balance"], "recent_transactions": [dict(t) for t in txns]}


def list_khata_customers(only_outstanding=True):
    conn = get_conn()
    try:
        if only_outstanding:
            rows = conn.execute(
                "SELECT name, balance FROM khata_customers WHERE balance > 0 ORDER BY balance DESC"
            ).fetchall()
        else:
            rows = conn.execute("SELECT name, balance FROM khata_customers ORDER BY name").fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]
