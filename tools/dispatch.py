from tools import inventory, billing, khata, analytics, documents, memory
from tools.errors import ToolError


def _wrap(fn, needs_chat_id=False, autofill_bill_id=False, is_document_tool=False):
    """
    Builds a uniform call(input_dict, chat_id, update_id, tool_call_id) wrapper
    around a plain tool function.

    Two things happen here that the model never controls directly:
      - bill_id, if omitted, is resolved from the chat's open draft (chat_sessions)
        rather than trusted purely from model output — the owner shouldn't have to
        repeat a bill number every message.
      - finalize_bill's idempotency_key is derived from (chat_id, telegram update_id),
        not accepted as a model-supplied argument at all (it's not even in the tool's
        JSON schema). That's what makes a redelivered Telegram update, or the agent
        retrying the same tool call, provably safe against double-billing.
    """

    def call(input_dict, chat_id=None, update_id=None, tool_call_id=None):
        kwargs = dict(input_dict)

        if autofill_bill_id and not kwargs.get("bill_id"):
            bid = billing.get_draft_bill_id(chat_id)
            if not bid:
                raise ToolError("There's no open bill for this chat. Call start_bill first.")
            kwargs["bill_id"] = bid

        if needs_chat_id:
            kwargs["chat_id"] = chat_id

        if fn is billing.finalize_bill:
            kwargs["idempotency_key"] = f"{chat_id}:{update_id}:{kwargs.get('bill_id')}"

        result = fn(**kwargs)
        file_path = result.get("path") if is_document_tool and isinstance(result, dict) else None
        return result, file_path

    return call


REGISTRY = {
    "find_product": _wrap(inventory.find_product),
    "add_product": _wrap(inventory.add_product),
    "receive_stock": _wrap(inventory.receive_stock),
    "get_stock_level": _wrap(inventory.get_stock_level),
    "list_low_stock": _wrap(inventory.list_low_stock),
    "list_products": _wrap(inventory.list_products),

    "start_bill": _wrap(billing.start_bill, needs_chat_id=True),
    "add_bill_item": _wrap(billing.add_bill_item, autofill_bill_id=True),
    "remove_bill_item": _wrap(billing.remove_bill_item, autofill_bill_id=True),
    "update_bill_item_qty": _wrap(billing.update_bill_item_qty, autofill_bill_id=True),
    "get_bill": _wrap(billing.get_bill),
    "finalize_bill": _wrap(billing.finalize_bill, autofill_bill_id=True),

    "add_khata_credit": _wrap(khata.add_khata_credit),
    "add_khata_payment": _wrap(khata.add_khata_payment),
    "get_khata_balance": _wrap(khata.get_khata_balance),
    "list_khata_customers": _wrap(khata.list_khata_customers),

    "get_daily_close": _wrap(analytics.get_daily_close),
    "get_sales_summary": _wrap(analytics.get_sales_summary),

    "generate_invoice_pdf": _wrap(documents.generate_invoice_pdf, is_document_tool=True),
    "generate_analysis_deck": _wrap(documents.generate_analysis_deck, is_document_tool=True),

    "get_preference": _wrap(memory.get_preference),
    "set_preference": _wrap(memory.set_preference),
    "list_preferences": _wrap(memory.list_preferences),
}


def dispatch_tool(name, input_dict, chat_id=None, update_id=None, tool_call_id=None):
    fn = REGISTRY.get(name)
    if not fn:
        return {"error": f"Unknown tool '{name}'"}, True, None
    try:
        result, file_path = fn(input_dict, chat_id=chat_id, update_id=update_id, tool_call_id=tool_call_id)
        return result, False, file_path
    except ToolError as e:
        return {"error": str(e)}, True, None
    except Exception as e:  # last-resort guard so a bug never crashes the whole turn
        return {"error": f"internal error: {e}"}, True, None
