"""Supervisor-owned monotonic renewal/telemetry loop, separate from computation."""
import threading
import time
from datetime import datetime

import httpx


class Maintenance:
    def __init__(self, base_url, headers, claim, current, observed_at):
        self.base_url, self.headers, self.claim = base_url, headers, claim
        self.stop_event, self.lost = threading.Event(), threading.Event()
        self.error = None
        self.trace = []
        self.sequence = 1
        self.cadence = claim["renew_after_seconds"]
        self.deadline = observed_at + (datetime.fromisoformat(current["lease_expires_at"])
                                      - datetime.fromisoformat(current["db_time"])).total_seconds()
        self.thread = threading.Thread(target=self.loop, name="relay-lease", daemon=True)

    def start(self):
        self.thread.start()

    def check(self):
        if self.lost.is_set() or time.monotonic() >= self.deadline:
            raise RuntimeError(self.error or "renewal_authority_lost")

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=16)
        if self.thread.is_alive(): raise RuntimeError("renewal_shutdown_failed")

    def loop(self):
        next_renew, next_heartbeat = time.monotonic() + self.cadence, time.monotonic()
        heartbeat_seq = 0
        sequence_started = None
        body = {k: self.claim[k] for k in ("job_id", "partition_id", "generation")}
        try:
            with httpx.Client(base_url=self.base_url, timeout=5, trust_env=False) as client:
                while not self.stop_event.is_set():
                    now = time.monotonic()
                    if now >= self.deadline:
                        self.error = "renewal_authority_lost"; self.lost.set(); return
                    if now >= next_renew:
                        if sequence_started is None: sequence_started = time.monotonic()
                        try:
                            response = client.post(f"/v1/attempts/{self.claim['attempt_id']}/renew",
                                headers=self.headers, json=body | {"sequence": str(self.sequence)})
                        except httpx.TransportError:
                            # Retry this renewal sequence only, never claim another attempt.
                            next_renew = time.monotonic() + 0.1; continue
                        if response.status_code == 503:
                            next_renew = time.monotonic() + 0.1; continue
                        if response.status_code != 200:
                            self.error = "renewal_authority_lost"; self.lost.set(); return
                        result = response.json()
                        # Conservative: time spent in transit does not add authority.
                        remaining = (datetime.fromisoformat(result["lease_expires_at"])
                                     - datetime.fromisoformat(result["db_time"])).total_seconds()
                        # A replay's db_time is its original logical result. Keep the
                        # first send time for this sequence across uncertain retries.
                        self.deadline = sequence_started + remaining
                        self.trace.append(result)
                        self.sequence += 1
                        sequence_started = None
                        next_renew = time.monotonic() + self.cadence
                    if time.monotonic() >= next_heartbeat:
                        heartbeat_seq += 1
                        try:
                            response = client.post(f"/v1/workers/{self.headers['X-Worker-Session']}/heartbeat",
                                headers=self.headers, json={"sequence": str(heartbeat_seq)})
                            if response.status_code in (401, 403):
                                self.error = "renewal_authority_lost"; self.lost.set(); return
                        except httpx.TransportError:
                            pass  # Telemetry never substitutes for an ownership acknowledgement.
                        next_heartbeat = time.monotonic() + 10
                    self.stop_event.wait(min(0.05, max(0, next_renew - time.monotonic())))
        except Exception:
            self.error = "renewal_authority_lost"; self.lost.set()
