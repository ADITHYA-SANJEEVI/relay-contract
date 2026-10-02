"""Bounded transport reconciliation; caller retains one durable identity."""
import time

import httpx


def retry_same(send, operation, inspect=None):
    for index in range(3):
        try:
            response = send()
            if response.status_code != 503:
                return response
        except httpx.TransportError:
            pass
        # A 503 (including unknown COMMIT) is not a negative acknowledgment.
        # Reads are informational; only the same operation can create authority.
        if inspect:
            try:
                inspect()
            except httpx.TransportError:
                pass
        if index < 2:
            time.sleep(0.1)
    raise RuntimeError(operation + "_outcome_uncertain")
