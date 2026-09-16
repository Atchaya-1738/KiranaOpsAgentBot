# Supermarket Ops Agent

Run a small Indian kirana store end-to-end from Telegram: receive stock, cut GST-correct
bills, run customer khata, close the day, and pull PDF invoices / PPTX analysis decks —
all in plain shopkeeper English, no menus, no admin panel.

> **On deployment:** this repo is a complete, runnable agent. I couldn't stand up a
> long-lived public process (with a real Telegram bot token) from the sandboxed environment
> I built this in — there's no persistent hosting there, and `api.telegram.org` isn't even
> reachable from it. What's here is everything needed to run it for real: `python main.py`
> with your own `ANTHROPIC_API_KEY` and `TELEGRAM_BOT_TOKEN` gets you a live bot in about a
> minute (see **Running it** below). I did not fabricate a bot handle or a recording.

---

## 1. Harness

**Choice: a hand-rolled control loop directly on the Anthropic Messages API's tool-use
primitive**, rather than Claude Agent SDK, a deep-agent framework, or Vercel AI SDK.

Why: the task's hard parts (oversell guard, idempotent finalize, atomic GST math, khata
consistency) all live in *how tool calls are dispatched and executed*, not in agent
scaffolding like subagents, planning, or multi-agent handoff — this is a single agent with
a rich, well-designed tool surface, not a multi-agent workflow. A thin loop keeps that
dispatch logic fully visible and testable (see `tests/` — everything in `tools/` is called
directly and asserted against, no framework mocking required), and it's `anthropic`-SDK-only
as a dependency, which matters for a 5-day hiring exercise. The brief explicitly lists
"or equivalent" — this is that.

The loop itself (`agent/orchestrator.py::run_turn`) is:

```
load short-term history from SQLite
  → messages.create(system, tools, messages)
  → if stop_reason == tool_use:
        execute every tool_use block via tools/dispatch.py
        feed tool_results back as the next user message
        loop (capped at 8 rounds per owner message)
    else:
        return the model's text
```

Business logic never lives in the loop or the system prompt — it lives in `tools/*.py`,
where the data actually changes. The loop's only jobs are orchestration and turning tool
errors into something the model can react to (`is_error: true` tool results).

## 2. Skill / tool design

Six modules, each a thin layer over SQLite, one dispatcher, no regex intent router:

| Module | Tools | Responsibility |
|---|---|---|
| `tools/inventory.py` | `find_product`, `add_product`, `receive_stock`, `get_stock_level`, `list_low_stock`, `list_products` | Catalog + stock-in |
| `tools/billing.py` | `start_bill`, `add_bill_item`, `remove_bill_item`, `update_bill_item_qty`, `get_bill`, `finalize_bill` | Multi-turn bill drafting, GST math, oversell guard |
| `tools/khata.py` | `add_khata_credit`, `add_khata_payment`, `get_khata_balance`, `list_khata_customers` | Credit ledger |
| `tools/analytics.py` | `get_daily_close`, `get_sales_summary` | Daily close, reporting aggregates |
| `tools/documents.py` | `generate_invoice_pdf`, `generate_analysis_deck` | Real PDF/PPTX artifacts |
| `tools/memory.py` | `get_preference`, `set_preference`, `list_preferences` | Standing owner preferences |

`tools/dispatch.py` is the one place that maps a model tool call to a Python function. It
also does two things the model is *never* trusted to do itself:
- resolves `bill_id` from the chat's open draft (`chat_sessions` table) when the model omits
  it, so the owner doesn't have to repeat a bill number every message;
- computes `finalize_bill`'s idempotency key server-side from `(chat_id, telegram update_id)`
  — it isn't even in that tool's JSON schema, so the model has no path to influence it.

The model decides *which* tools to call and *in what order* for a given message (e.g. "make
it 6 Maggi" → `update_bill_item_qty`; "drop the butter" → `remove_bill_item`); nothing here
pattern-matches the owner's phrasing.

## 3. The hard parts

**Grounding.** Every price, GST rate, HSN code, and stock figure the model states comes back
from a tool call (`find_product`, `get_stock_level`, `get_bill`, ...). The system prompt says
"never invent a price" but that's a backstop, not the mechanism — the mechanism is that
`add_bill_item` looks up `sell_price`/`gst_rate` from the `products` row itself; the model
can't pass a price in even if it wanted to (it's not a parameter on that tool).

**Oversell guard.** `finalize_bill` decrements stock with a single conditional UPDATE per
line: `qty_on_hand = qty_on_hand - ? WHERE id=? AND qty_on_hand >= ?`. If `rowcount == 0` the
whole finalize raises `ToolError` before any other line is touched or the bill is marked
finalized — refused at the data layer, not hoped for in the prompt. See
`tools/billing.py::finalize_bill`.

**GST correctness.** Each line stores its own HSN and slab; `_line_amounts()` splits the slab
into CGST/SGST halves and rounds each line half-up to 2 decimals before summing (not summing
then rounding, which would drift). The invoice total itself rounds to the nearest rupee with
an explicit `round_off` line, matching how a real kirana bill is written.

**Multi-turn bills.** A bill is a `draft` row from `start_bill` until `finalize_bill`. Every
edit tool (`add_bill_item`, `remove_bill_item`, `update_bill_item_qty`) checks
`status == 'draft'` first and returns a running total after every change. Stock is untouched
until finalize — so an abandoned draft (owner walks away mid-bill) never affects inventory.

**Idempotency.** Two layers: (1) the Telegram layer records every `update_id` it starts
processing in `telegram_updates_seen` and skips redeliveries before they reach the agent at
all; (2) `finalize_bill` itself is idempotent on a server-derived key
(`chat_id:update_id:bill_id`), stored as a `UNIQUE` column on `bills`. If that key has
already been finalized, the second call returns the original result untouched — verified in
the smoke test below, where calling `finalize_bill` twice with the same key decrements stock
exactly once.

**Concurrency.** All stock/bill/khata mutations run inside `db.database.immediate_transaction()`,
which issues `BEGIN IMMEDIATE` — SQLite takes the write lock at the start of the transaction,
not on first write, so a sale and a simultaneous stock-in on the same product serialize
instead of interleaving. Combined with the conditional-UPDATE oversell check, there's no
read-then-write window for a race to land in.

**Guardrails beyond the brief's examples:** `add_product` refuses a sell price below cost;
`add_khata_payment` refuses settling more than the customer's outstanding balance; editing or
re-finalizing a non-draft bill is refused; a credit sale without a customer name on the bill
is refused rather than silently defaulting to "walk-in".

**Real artifacts.** `tools/documents.py` builds the invoice with `reportlab` (proper table,
CGST/SGST breakup, shop letterhead from preferences) and the analysis deck with native
`python-pptx` charts (`COLUMN_CLUSTERED` for daily sales, `BAR_CLUSTERED` for top items) —
not screenshots, not a text dump into a slide.

**Memory across sessions.** `preferences` is a separate table from `conversation_messages`.
The system prompt is rebuilt fresh on every single API call from `list_preferences()`
(`agent/orchestrator.py::_system_prompt`), so a preference set last week applies to a message
sent after `/new` with zero conversation history — it's living outside the transcript, not
smuggled into it. `/new` only truncates `conversation_messages` and `chat_sessions` for that
chat; `products`, `bills`, `khata_*`, and `preferences` are untouched.

## 4. Persistence

SQLite in WAL mode (`db/schema.sql`, `db/database.py`), one file, survives a restart. No
in-memory state anywhere in `tools/` — every tool opens its own connection.

## 5. Running it

```bash
git clone <this repo> && cd kirana-ops-agent
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# fill in ANTHROPIC_API_KEY and TELEGRAM_BOT_TOKEN (from @BotFather)

python main.py
```

First run creates `data/store.db`, seeds a starter catalog of real SKUs (Aashirvaad Atta,
Tata Salt, Amul Butter, Fortune oil, Maggi, Parle-G, Surf Excel, plus loose sugar/rice/dal),
and starts long-polling. Message the bot; `/new` starts a fresh chat without losing store
state.

## 6. Smoke-tested end to end (see commit history)

Before wiring Telegram, every hard part was exercised directly against `tools/`:
multi-item draft → edit → drop item → finalize; oversell attempt correctly refused with
stock unchanged; `finalize_bill` called twice with the same idempotency key decrements
stock exactly once; khata credit → payment → overpayment refused; PDF invoice and PPTX deck
both generate and render correctly (invoice checked by rasterizing to PNG).

## 7. What I'd add next (stretch, not done)

Branded invoice templates, scheduled weekly decks, reorder suggestions from sales velocity,
expiry/FEFO tracking, voice-note billing, Hindi/Tamil support, barcode lookup, khata
reminders — the tool surface here is deliberately structured so each of these is a new tool
in an existing module (e.g. `list_khata_customers` → a scheduled reminder job) rather than a
rearchitecture.
