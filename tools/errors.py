class ToolError(Exception):
    """
    Raised for any business-rule refusal: oversell, ambiguous product, bad unit,
    missing khata, editing a finalized bill, etc. The dispatcher catches this and
    returns it to the model as a tool_result with is_error=True, so the model sees
    *why* it was refused and can explain it to the owner or ask a clarifying
    question — instead of the process crashing or silently doing the wrong thing.
    """
    pass
