"""Single-use pairing and one volatile, absolutely bounded local session."""

import hashlib
import secrets
import time

PAIR_SECONDS = 120
SESSION_SECONDS = 1800
COOKIE = "relay_board_session"


def digest(value):
    return hashlib.sha256(value.encode()).digest()


class Sessions:
    def __init__(self, pairing_code, clock=time.monotonic):
        self.clock = clock
        self.pair_hash = digest(pairing_code)
        self.pair_deadline = clock() + PAIR_SECONDS
        self.session_hash = None
        self.session_deadline = 0
        self.remaining_guesses = 32

    def pair(self, code):
        if self.remaining_guesses <= 0 or self.pair_hash is None or self.clock() >= self.pair_deadline:
            return None
        self.remaining_guesses -= 1
        if not secrets.compare_digest(digest(code), self.pair_hash):
            return None
        self.pair_hash = None
        token = secrets.token_urlsafe(32)
        self.session_hash = digest(token)
        self.session_deadline = self.clock() + SESSION_SECONDS
        return token

    def valid(self, token):
        if self.clock() >= self.session_deadline:
            self.session_hash = None
        return bool(self.session_hash and token and len(token) <= 128
                    and secrets.compare_digest(digest(token), self.session_hash))

    def logout(self):
        self.session_hash = None

    def snapshot(self):
        return {"authenticated": True, "mode": "local_read_session",
                "expires_in_seconds": max(0, int(self.session_deadline - self.clock()))}
