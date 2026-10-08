def normalize_whitespace(text):
    """Normalize Unicode whitespace; require a string."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    return " ".join(text.split())
