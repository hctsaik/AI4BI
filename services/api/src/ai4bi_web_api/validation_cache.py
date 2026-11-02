"""Bounded validation proofs, independent of the analysis runtime."""
from collections import OrderedDict
import threading


class QueryValidationCache:
    """Bounded, app-owned success proofs; never retain frames or query results."""
    def __init__(self, max_entries=256):
        if not 1 <= max_entries <= 256:
            raise ValueError("Validation cache capacity must be between 1 and 256")
        self.max_entries = max_entries
        self._verified = OrderedDict()
        self._lock = threading.Lock()

    def run(self, fingerprint, action):
        with self._lock:
            if fingerprint in self._verified:
                self._verified.move_to_end(fingerprint)
                return
        action()  # A failed validation must never become a success proof.
        with self._lock:
            self._verified[fingerprint] = None
            self._verified.move_to_end(fingerprint)
            while len(self._verified) > self.max_entries:
                self._verified.popitem(last=False)
