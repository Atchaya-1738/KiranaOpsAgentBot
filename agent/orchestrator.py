import os
import json
import re

from google import genai
from google.genai import types

from db.database import get_conn
from tools.schemas import TOOLS_SCHEMA
from tools.dispatch import dispatch_tool
from tools.memory import list_preferences


# ---------------------------------------------------------
# Gemini client
# ---------------------------------------------------------

client = genai.Client(
    api_key=os.environ["GEMINI_API_KEY"]
)

MODEL = os.environ.get(
    "GEMINI_MODEL",
    "gemini-3.6-flash"
)

MAX_TOOL_ROUNDS = 8


# ---------------------------------------------------------
# Conversation history
# ---------------------------------------------------------

def _load_history(chat_id, limit=30):
    """
    Load the last N conversation messages from SQLite.
    """

    conn = get_conn()

    try:
        rows = conn.execute(
            """
            SELECT role, content
            FROM conversation_messages
            WHERE chat_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (chat_id, limit),
        ).fetchall()

    finally:
        conn.close()

    rows = list(reversed(rows))

    return [
        {
            "role": r["role"],
            "content": r["content"],
        }
        for r in rows
    ]


def _save_message(chat_id, role, content):
    conn = get_conn()

    try:
        conn.execute(
            """
            INSERT INTO conversation_messages(chat_id, role, content)
            VALUES (?, ?, ?)
            """,
            (chat_id, role, content),
        )

        conn.commit()

    finally:
        conn.close()


# ---------------------------------------------------------
# Clean Telegram text
# ---------------------------------------------------------

def _clean_telegram_text(text):
    """
    Remove Markdown formatting because the Telegram bot
    sends plain text and would otherwise show ** characters.
    """

    if not text:
        return ""

    # Remove bold markers
    text = text.replace("**", "")

    # Remove underline markers
    text = text.replace("__", "")

    # Remove simple italic markers
    text = text.replace("*", "")

    # Remove inline code markers
    text = text.replace("`", "")

    # Remove Markdown heading markers at the beginning
    text = re.sub(
        r"(?m)^\s*#+\s*",
        "",
        text
    )

    return text.strip()


# ---------------------------------------------------------
# System prompt
# ---------------------------------------------------------

def _system_prompt():

    prefs = list_preferences()

    prefs_text = "\n".join(
        f"- {k}: {v}"
        for k, v in prefs.items()
    ) or "(none set yet)"

    return f"""
You are the operations agent for an Indian kirana / supermarket,
reachable on Telegram by the shop owner.

You run the shop end-to-end:

- receiving stock
- checking stock
- cutting bills
- GST calculations
- customer khata
- daily close
- invoices
- analysis decks
- store preferences

The owner writes in short, casual shopkeeper English.

Examples:

"2kg sugar"
"1 atta"
"what's running out?"
"how much stock do we have?"
"make bill for 2 maggi"
"customer Ravi paid 200"


STANDING OWNER PREFERENCES

These preferences persist across chats and restarts.

{prefs_text}


RULES:

1. Never invent a product, price, GST rate, HSN code,
   or stock quantity.

2. Always use the appropriate tool to look up information.

3. If a request is genuinely ambiguous, ask a short
   clarification question instead of guessing.

4. Bills are built over multiple messages.

5. Start a bill when needed.

6. Add, remove, or update bill items as requested.

7. Only finalize a bill when the owner clearly confirms
   the sale is complete.

8. A payment mode such as cash or UPI is usually a signal
   that the bill is ready to finalize.

9. Show a running total after bill changes.

10. If a tool refuses an action, explain the reason clearly.
    Do not blindly retry the same action.

11. If the owner gives a standing preference such as:

    "always assume UPI"
    "default atta is Aashirvaad 5kg"

    call set_preference so that it is actually saved.

12. Keep replies short and shopkeeper-friendly.

13. Use ₹ for money.

14. State totals clearly.

15. When asked for an invoice or analysis deck,
    call the appropriate document tool.

16. Do not claim that something was completed unless
    the corresponding tool succeeded.

17. Use plain text only.

18. Do NOT use Markdown formatting.

19. Do NOT use **bold**, *italics*, __underline__,
    backticks, Markdown headings, or other Markdown symbols.

20. For lists, use simple hyphens such as:
    - Sugar: 60 kg
    - Rice: 60 kg

21. Never put unnecessary symbols around product names.
"""


# ---------------------------------------------------------
# Convert existing tool schemas
# ---------------------------------------------------------

def _convert_tool_schema(schema):
    """
    Convert the existing Anthropic-style tool schema
    into Gemini function declaration format.
    """

    name = schema.get("name", "")
    description = schema.get("description", "")

    input_schema = schema.get(
        "input_schema",
        schema.get("parameters", {})
    )

    return types.FunctionDeclaration(
        name=name,
        description=description,
        parameters=input_schema,
    )


def _build_tools():

    declarations = []

    for schema in TOOLS_SCHEMA:

        try:
            declaration = _convert_tool_schema(schema)

            declarations.append(
                declaration
            )

        except Exception as e:

            print(
                f"Warning: Could not convert tool "
                f"{schema.get('name', 'unknown')}: {e}"
            )

    return [
        types.Tool(
            function_declarations=declarations
        )
    ]


GEMINI_TOOLS = _build_tools()


# ---------------------------------------------------------
# Convert database history to Gemini contents
# ---------------------------------------------------------

def _build_contents(history, user_text):

    contents = []

    for message in history:

        role = message["role"]

        if role == "user":

            contents.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            text=message["content"]
                        )
                    ],
                )
            )

        elif role == "assistant":

            contents.append(
                types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            text=message["content"]
                        )
                    ],
                )
            )

    contents.append(
        types.Content(
            role="user",
            parts=[
                types.Part(
                    text=user_text
                )
            ],
        )
    )

    return contents


# ---------------------------------------------------------
# Tool execution
# ---------------------------------------------------------

def _execute_tool(
    function_call,
    chat_id,
    update_id,
):

    tool_name = function_call.name

    tool_args = dict(
        function_call.args or {}
    )

    result, is_error, file_path = dispatch_tool(
        tool_name,
        tool_args,
        chat_id=chat_id,
        update_id=update_id,
        tool_call_id=f"gemini_{tool_name}",
    )

    return result, is_error, file_path


# ---------------------------------------------------------
# Main agent turn
# ---------------------------------------------------------

def run_turn(
    chat_id,
    update_id,
    user_text
):

    history = _load_history(chat_id)

    _save_message(
        chat_id,
        "user",
        user_text,
    )

    contents = _build_contents(
        history,
        user_text,
    )

    generated_files = []

    final_text_parts = []

    for _ in range(MAX_TOOL_ROUNDS):

        response = client.models.generate_content(
            model=MODEL,

            contents=contents,

            config=types.GenerateContentConfig(
                system_instruction=_system_prompt(),

                tools=GEMINI_TOOLS,

                temperature=0.2,

                max_output_tokens=2000,
            ),
        )

        # -------------------------------------------------
        # Check response
        # -------------------------------------------------

        if not response.candidates:

            final_text_parts = [
                "I couldn't get a response from the AI. "
                "Please try again."
            ]

            break

        candidate = response.candidates[0]

        parts = candidate.content.parts

        function_calls = []

        text_parts = []

        # -------------------------------------------------
        # Read response parts
        # -------------------------------------------------

        for part in parts:

            if getattr(part, "text", None):

                text_parts.append(
                    part.text
                )

            if getattr(part, "function_call", None):

                function_calls.append(
                    part.function_call
                )

        # -------------------------------------------------
        # No tool call = final answer
        # -------------------------------------------------

        if not function_calls:

            final_text_parts = text_parts

            break

        # -------------------------------------------------
        # Add model response to conversation
        # -------------------------------------------------

        contents.append(
            candidate.content
        )

        # -------------------------------------------------
        # Execute requested tools
        # -------------------------------------------------

        tool_response_parts = []

        for function_call in function_calls:

            try:

                result, is_error, file_path = _execute_tool(
                    function_call,
                    chat_id,
                    update_id,
                )

                if file_path:

                    generated_files.append(
                        file_path
                    )

                tool_response_parts.append(
                    types.Part.from_function_response(
                        name=function_call.name,

                        response={
                            "result": result,
                            "is_error": is_error,
                        },
                    )
                )

            except Exception as e:

                print(
                    f"Tool error in {function_call.name}: {e}"
                )

                tool_response_parts.append(
                    types.Part.from_function_response(
                        name=function_call.name,

                        response={
                            "result": str(e),
                            "is_error": True,
                        },
                    )
                )

        # -------------------------------------------------
        # Send tool results back to Gemini
        # -------------------------------------------------

        contents.append(
            types.Content(
                role="user",
                parts=tool_response_parts,
            )
        )

    else:

        final_text_parts = [
            "That took more steps than expected. "
            "Could you rephrase or simplify the request?"
        ]

    # -----------------------------------------------------
    # Build final response
    # -----------------------------------------------------

    final_text = "\n".join(
        p for p in final_text_parts
        if p
    ).strip()

    if not final_text:

        final_text = "Done."

    # -----------------------------------------------------
    # Remove Markdown before sending to Telegram
    # -----------------------------------------------------

    final_text = _clean_telegram_text(
        final_text
    )

    # -----------------------------------------------------
    # Save assistant response
    # -----------------------------------------------------

    _save_message(
        chat_id,
        "assistant",
        final_text,
    )

    return final_text, generated_files