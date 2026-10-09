"""Client text that PostgreSQL text/JSONB cannot store is rejected at the request boundary."""


def reject_nul(value):
    """Return value unchanged, or raise ValueError when a string (or any string nested in it) has NUL."""
    if isinstance(value, str):
        if "\x00" in value:
            raise ValueError("NUL characters are not supported")
    elif isinstance(value, dict):
        for key, entry in value.items():
            reject_nul(key)
            reject_nul(entry)
    elif isinstance(value, (list, tuple)):
        for entry in value:
            reject_nul(entry)
    return value
