"""
Seeds a starter catalog of real Indian kirana SKUs so the bot is immediately
usable in a demo, without first having to `add_product` everything by hand.
Only runs if the products table is empty.
"""
from db.database import get_conn
from tools import inventory

# name, brand, unit, is_loose, hsn, gst%, cost, mrp, sell, reorder_level, initial_qty
CATALOG = [
    ("Atta 5kg", "Aashirvaad", "packet", False, "1101", 5, 210, 260, 255, 5, 20),
    ("Salt 1kg", "Tata", "packet", False, "2501", 5, 18, 25, 24, 10, 40),
    ("Butter 100g", "Amul", "packet", False, "0405", 12, 48, 62, 60, 10, 30),
    ("Sunflower Oil 1L", "Fortune", "packet", False, "1512", 5, 120, 145, 140, 10, 25),
    ("Maggi 70g", "Nestle", "packet", False, "1902", 12, 10, 14, 14, 20, 60),
    ("Parle-G", "Parle", "packet", False, "1905", 18, 8, 10, 10, 20, 50),
    ("Surf Excel 1kg", "HUL", "packet", False, "3402", 18, 95, 130, 125, 10, 20),
    ("Sugar", None, "kg", True, "1701", 0, 38, 45, 44, 15, 60),
    ("Rice", None, "kg", True, "1006", 0, 40, 55, 52, 15, 60),
    ("Toor Dal", None, "kg", True, "0713", 0, 95, 130, 125, 8, 30),
]


def seed_if_empty():
    conn = get_conn()
    try:
        count = conn.execute("SELECT COUNT(*) c FROM products").fetchone()["c"]
    finally:
        conn.close()
    if count > 0:
        return

    for name, brand, unit, is_loose, hsn, gst, cost, mrp, sell, reorder, qty in CATALOG:
        inventory.add_product(
            name=name, brand=brand, unit=unit, is_loose=is_loose, hsn_code=hsn,
            gst_rate=gst, cost_price=cost, mrp=mrp, sell_price=sell,
            reorder_level=reorder, initial_qty=qty,
        )
