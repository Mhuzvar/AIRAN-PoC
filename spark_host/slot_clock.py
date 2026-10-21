#!/usr/bin/env python3

import os
import time

SLOTS_PER_TICK = 128
SLOT_DURATION_MS = {
    0: 1.0,
    1: 0.5,
    2: 0.25,
}


class SlotClock:

    def __init__(self, log_path: str, numerology: int = 1, poll_interval: float = 0.05):
        self.log_path = log_path
        self.tick_ms = SLOTS_PER_TICK * SLOT_DURATION_MS[numerology]
        self.poll_interval = poll_interval
        self._fh = None
        self._ticks_seen = 0

    def _ensure_open(self):
        while self._fh is None:
            if os.path.exists(self.log_path):
                self._fh = open(self.log_path, "r")
                self._fh.seek(0, os.SEEK_END)
            else:
                print(f"[slot_clock] Waiting for log file: {self.log_path}")
                time.sleep(1.0)

    def _poll_new_ticks(self) -> int:
        self._ensure_open()
        new_ticks = 0
        where = self._fh.tell()
        line = self._fh.readline()
        while line:
            if "[NR_MAC] Frame.Slot" in line:
                new_ticks += 1
            where = self._fh.tell()
            line = self._fh.readline()
        self._fh.seek(where)
        return new_ticks

    def wait_ticks(self, n: int) -> None:
        remaining = n
        while remaining > 0:
            got = self._poll_new_ticks()
            remaining -= got
            self._ticks_seen += got
            if remaining > 0:
                time.sleep(self.poll_interval)

    def wait_sim_seconds(self, sim_seconds: float) -> None:
        ticks_needed = max(1, round((sim_seconds * 1000.0) / self.tick_ms))
        self.wait_ticks(ticks_needed)

    def close(self):
        if self._fh:
            self._fh.close()
            self._fh = None


if __name__ == "__main__":
    import sys
    log_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/gnb_log.txt"
    clock = SlotClock(log_path)
    print(f"Waiting for 5.0s of SIMULATED time (log: {log_path})...")
    t0 = time.time()
    clock.wait_sim_seconds(5.0)
    elapsed_real = time.time() - t0
    print(f"5.0s of simulated time elapsed in {elapsed_real:.1f}s of real time "
          f"(slowdown ~{elapsed_real/5.0:.1f}x)")