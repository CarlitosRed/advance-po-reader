"""Stable errors without document content, SQL parameters or provider secrets."""
class BackendError(Exception):
    def __init__(self, code: str, status: int = 400):
        self.code = code
        self.status = status
        super().__init__(code)
