import re
from typing import Optional

def safe_calc(expression: str) -> Optional[str]:
    """
    A very safe local calculator for basic arithmetic.
    Supported: + - * / ^ ( ) decimals integers
    """
    # Clean expression
    expr = expression.strip().lower()
    if expr.startswith("what is "):
        expr = expr[8:].strip()
    if expr.endswith("?"):
        expr = expr[:-1].strip()
        
    # Strictly allow only math characters
    if not re.match(r'^[0-9\+\-\*\/\^\(\)\.\s]+$', expr):
        return None
        
    # Cap length to prevent complex nested bombs
    if len(expr) > 200:
        return None

    # Pre-process for python-style operators
    expr = expr.replace('^', '**')
    
    try:
        # Use simple eval with NO globals or locals for safety
        # This is still slightly risky but restricted by the regex above
        result = eval(expr, {"__builtins__": {}}, {})
        return str(result)
    except Exception:
        return None

def is_math_query(text: str) -> bool:
    text = text.lower().strip()
    if text.startswith("what is ") and any(c in text for c in "+-*/^"):
        return True
    # If it's just numbers and math ops
    if re.match(r'^[0-9\+\-\*\/\^\(\)\.\s\?]+$', text) and any(c in text for c in "+-*/^"):
        return True
    return False
