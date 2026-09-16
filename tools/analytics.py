from datetime import date

from db.database import get_conn


def get_daily_close(for_date=None):
    d = for_date or date.today().isoformat()
    conn = get_conn()
    try:
        bills = conn.execute(
            "SELECT * FROM bills WHERE status = 'finalized' AND date(finalized_at) = date(?)", (d,)
        ).fetchall()
        if not bills:
            return {
                "date": d, "total_sales": 0, "cgst_collected": 0, "sgst_collected": 0,
                "bill_count": 0, "by_payment_mode": {}, "top_items": [],
            }
        by_mode = {}
        for b in bills:
            by_mode[b["payment_mode"]] = by_mode.get(b["payment_mode"], 0) + b["total"]
        bill_ids = [b["id"] for b in bills]
        placeholders = ",".join("?" * len(bill_ids))
        top = conn.execute(
            f"SELECT product_name, SUM(qty) qty, SUM(line_total) revenue FROM bill_items "
            f"WHERE bill_id IN ({placeholders}) GROUP BY product_name ORDER BY revenue DESC LIMIT 5",
            bill_ids,
        ).fetchall()
    finally:
        conn.close()

    return {
        "date": d,
        "total_sales": round(sum(b["total"] for b in bills), 2),
        "cgst_collected": round(sum(b["cgst_total"] for b in bills), 2),
        "sgst_collected": round(sum(b["sgst_total"] for b in bills), 2),
        "bill_count": len(bills),
        "by_payment_mode": {k: round(v, 2) for k, v in by_mode.items()},
        "top_items": [dict(t) for t in top],
    }


def get_sales_summary(start_date, end_date):
    conn = get_conn()
    try:
        bills = conn.execute(
            "SELECT * FROM bills WHERE status = 'finalized' AND date(finalized_at) BETWEEN date(?) AND date(?)",
            (start_date, end_date),
        ).fetchall()
        by_day = {}
        for b in bills:
            day = (b["finalized_at"] or "")[:10]
            by_day[day] = by_day.get(day, 0) + b["total"]

        top_items = []
        bill_ids = [b["id"] for b in bills]
        if bill_ids:
            placeholders = ",".join("?" * len(bill_ids))
            top_items = [
                dict(r) for r in conn.execute(
                    f"SELECT product_name, SUM(qty) qty, SUM(line_total) revenue FROM bill_items "
                    f"WHERE bill_id IN ({placeholders}) GROUP BY product_name ORDER BY revenue DESC LIMIT 8",
                    bill_ids,
                ).fetchall()
            ]

        low_stock = conn.execute(
            "SELECT name, qty_on_hand, unit, reorder_level FROM products WHERE qty_on_hand <= reorder_level"
        ).fetchall()
    finally:
        conn.close()

    return {
        "start_date": start_date, "end_date": end_date,
        "total_sales": round(sum(b["total"] for b in bills), 2),
        "cgst_collected": round(sum(b["cgst_total"] for b in bills), 2),
        "sgst_collected": round(sum(b["sgst_total"] for b in bills), 2),
        "bill_count": len(bills),
        "by_day": {k: round(v, 2) for k, v in by_day.items()},
        "top_items": top_items,
        "low_stock": [dict(r) for r in low_stock],
    }
