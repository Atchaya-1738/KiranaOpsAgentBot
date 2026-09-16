"""
Direct tests against tools/*.py — no Telegram, no Anthropic API needed, since
all business logic lives at this layer, not in the model or the control loop.

Run with:  DB_PATH=/tmp/kirana_test.db pytest tests/ -v
(each test resets the DB via the `fresh_db` fixture, so order doesn't matter)
"""
import os
import sys
import importlib

import pytest

TEST_DB = "/tmp/kirana_test_core.db"


@pytest.fixture
def fresh_db(monkeypatch):
    for f in (TEST_DB, TEST_DB + "-wal", TEST_DB + "-shm"):
        if os.path.exists(f):
            os.remove(f)
    monkeypatch.setenv("DB_PATH", TEST_DB)

    # db.database reads DB_PATH at import time, so force a clean reimport
    for mod in list(sys.modules):
        if mod.startswith("db.") or mod.startswith("tools.") or mod == "db":
            del sys.modules[mod]

    db = importlib.import_module("db.database")
    db.init_db()

    inventory = importlib.import_module("tools.inventory")
    inventory.add_product(
        name="Sugar", unit="kg", is_loose=True, hsn_code="1701", gst_rate=0,
        cost_price=38, mrp=45, sell_price=44, reorder_level=15, initial_qty=10,
    )
    inventory.add_product(
        name="Atta 5kg", brand="Aashirvaad", unit="packet", hsn_code="1101", gst_rate=5,
        cost_price=210, mrp=260, sell_price=255, reorder_level=5, initial_qty=20,
    )
    return importlib.import_module("tools.billing"), importlib.import_module("tools.khata"), inventory


def test_multi_turn_bill_and_gst_math(fresh_db):
    billing, khata, inventory = fresh_db
    b = billing.start_bill("chat-1")
    billing.add_bill_item(b["bill_id"], "Sugar", 2)         # 0% GST
    r = billing.add_bill_item(b["bill_id"], "Atta", 1)       # 5% GST -> 2.5 CGST + 2.5 SGST

    assert r["subtotal"] == 88.0 + 255.0
    assert r["cgst_total"] == pytest.approx(6.38, abs=0.01)
    assert r["sgst_total"] == pytest.approx(6.38, abs=0.01)


def test_edit_before_finalize_does_not_touch_stock(fresh_db):
    billing, khata, inventory = fresh_db
    b = billing.start_bill("chat-2")
    billing.add_bill_item(b["bill_id"], "Atta", 3)
    billing.remove_bill_item(b["bill_id"], product_query="Atta")
    stock = inventory.get_stock_level("Atta")[0]
    assert stock["qty_on_hand"] == 20  # unchanged: nothing finalized yet


def test_oversell_guard_refuses_and_leaves_stock_untouched(fresh_db):
    billing, khata, inventory = fresh_db
    b = billing.start_bill("chat-3")
    billing.add_bill_item(b["bill_id"], "Sugar", 999)  # only 10kg in stock
    with pytest.raises(billing.ToolError if hasattr(billing, "ToolError") else Exception):
        billing.finalize_bill(b["bill_id"], payment_mode="cash", idempotency_key="k1")
    assert inventory.get_stock_level("Sugar")[0]["qty_on_hand"] == 10


def test_finalize_is_idempotent(fresh_db):
    billing, khata, inventory = fresh_db
    b = billing.start_bill("chat-4")
    billing.add_bill_item(b["bill_id"], "Sugar", 2)
    key = "chat-4:42:" + str(b["bill_id"])

    r1 = billing.finalize_bill(b["bill_id"], payment_mode="cash", idempotency_key=key)
    r2 = billing.finalize_bill(b["bill_id"], payment_mode="cash", idempotency_key=key)

    assert r1["already_processed"] is False
    assert r2["already_processed"] is True
    assert inventory.get_stock_level("Sugar")[0]["qty_on_hand"] == 8  # decremented once, not twice


def test_khata_cycle_and_overpayment_guard(fresh_db):
    billing, khata, inventory = fresh_db
    khata.add_khata_credit("Ramesh", 500)
    khata.add_khata_payment("Ramesh", 300)
    bal = khata.get_khata_balance("Ramesh")
    assert bal["balance"] == 200

    with pytest.raises(Exception):
        khata.add_khata_payment("Ramesh", 10000)


def test_credit_sale_updates_khata_atomically_with_bill(fresh_db):
    billing, khata, inventory = fresh_db
    b = billing.start_bill("chat-5", customer_name="Suresh")
    billing.add_bill_item(b["bill_id"], "Sugar", 1)
    billing.finalize_bill(b["bill_id"], payment_mode="credit", idempotency_key="k-credit")
    bal = khata.get_khata_balance("Suresh")
    assert bal["balance"] > 0
