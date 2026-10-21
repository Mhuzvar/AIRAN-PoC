#!/usr/bin/env python3

import argparse
import csv
import errno
import math
import os
import random
import sys
import time
from contextlib import contextmanager
from datetime import datetime

from oai_telnet import channelmod_modify
from slot_clock import SlotClock

CARRIER_FREQ_GHZ = 3.6192
UE_HEIGHT_M = 1.5

D_MIN = 10.0
MOBILITY_MAX_DB = 15.0

MAX_STEP_M = 10.0
TREND_MIN_STEPS = 3
TREND_MAX_STEPS = 8

DEFAULT_LOCK_PATH = "/tmp/sbx_iface_API.lock"
DEFAULT_LOCK_TIMEOUT = 30.0
LOCK_POLL_INTERVAL = 0.1
DEFAULT_STALE_AFTER = 60.0


def umi_nlos_pathloss(distance_m: float) -> float:
    d = max(distance_m, 1.0)
    return (35.3 * math.log10(d)
            + 22.4
            + 21.3 * math.log10(CARRIER_FREQ_GHZ)
            - 0.3 * (UE_HEIGHT_M - 1.5))


def pathloss_to_distance(ploss_db: float) -> float:
    exponent = (ploss_db - 22.4 - 21.3 * math.log10(CARRIER_FREQ_GHZ)
                + 0.3 * (UE_HEIGHT_M - 1.5)) / 35.3
    return 10 ** exponent


PL_OFFSET_DB = None


def real_to_sim_ploss(pl_real_db: float) -> float:
    return min(max(pl_real_db - PL_OFFSET_DB, 0.0), MOBILITY_MAX_DB)


PL_OFFSET_DB = umi_nlos_pathloss(D_MIN)
D_MAX = pathloss_to_distance(PL_OFFSET_DB + MOBILITY_MAX_DB)


def _lock_owner(lock_path: str) -> str:
    try:
        with open(lock_path) as f:
            return f.read().strip() or "?"
    except OSError:
        return "?"


def _pid_alive(pid_text: str) -> bool:
    try:
        pid = int(pid_text)
    except (TypeError, ValueError):
        return True
    if pid <= 0:
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        return exc.errno != errno.ESRCH
    return True


def _is_stale(lock_path: str, stale_after: float) -> bool:
    if stale_after <= 0:
        return False
    if not _pid_alive(_lock_owner(lock_path)):
        return True
    try:
        age = time.time() - os.path.getmtime(lock_path)
    except OSError:
        return False
    return age > stale_after


def wait_for_unlock(lock_path: str = DEFAULT_LOCK_PATH,
                    poll: float = LOCK_POLL_INTERVAL,
                    timeout: float = DEFAULT_LOCK_TIMEOUT,
                    verbose: bool = True) -> float:
    if not os.path.exists(lock_path):
        return 0.0

    start = time.monotonic()
    if verbose:
        print(f"[lock] waiting for {lock_path} to be released (pid {_lock_owner(lock_path)}) ...")

    while os.path.exists(lock_path):
        waited = time.monotonic() - start
        if waited > timeout:
            print(f"[lock] WARNING: {lock_path} still present after {waited:.1f} s "
                  f"- continuing despite the lock (possibly a stale lock)")
            return waited
        time.sleep(poll)

    waited = time.monotonic() - start
    if verbose and waited > 0:
        print(f"[lock] released after {waited:.2f} s")
    return waited


@contextmanager
def api_lock(lock_path: str = DEFAULT_LOCK_PATH,
             poll: float = LOCK_POLL_INTERVAL,
             timeout: float = DEFAULT_LOCK_TIMEOUT,
             claim: bool = True,
             stale_after: float = DEFAULT_STALE_AFTER,
             verbose: bool = True):
    if not claim:
        yield wait_for_unlock(lock_path, poll, timeout, verbose)
        return

    start = time.monotonic()
    fd = None
    announced = False

    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            break
        except FileExistsError:
            if not announced and verbose:
                print(f"[lock] held by pid {_lock_owner(lock_path)}, waiting ...")
                announced = True

            if _is_stale(lock_path, stale_after):
                print(f"[lock] WARNING: stale lock {lock_path} "
                      f"(pid {_lock_owner(lock_path)}) - removing and taking over")
                try:
                    os.unlink(lock_path)
                except FileNotFoundError:
                    pass
                continue

            waited = time.monotonic() - start
            if waited > timeout:
                print(f"[lock] WARNING: failed to acquire {lock_path} within {waited:.1f} s "
                      f"- calling the API WITHOUT the lock")
                yield None
                return
            time.sleep(poll)

    waited = time.monotonic() - start
    if verbose and waited > 0:
        print(f"[lock] acquired after {waited:.2f} s (pid {os.getpid()})")

    try:
        try:
            os.write(fd, f"{os.getpid()}\n".encode())
        finally:
            os.close(fd)
            fd = None
        yield waited
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.unlink(lock_path)
        except FileNotFoundError:
            pass


class WalkingUE:

    def __init__(self, ue_index: int, start_distance: float):
        self.ue_index = ue_index
        self.channel_id = ue_index - 1
        self.distance = start_distance
        self.trend_direction = random.choice([-1, 1])
        self.trend_steps_left = random.randint(TREND_MIN_STEPS, TREND_MAX_STEPS)

    def _reroll_trend(self):
        self.trend_direction = random.choice([-1, 1])
        self.trend_steps_left = random.randint(TREND_MIN_STEPS, TREND_MAX_STEPS)

    def step(self, dt: float = None) -> float:
        if self.trend_steps_left <= 0:
            self._reroll_trend()

        step_distance = random.uniform(0.0, MAX_STEP_M)
        self.distance += self.trend_direction * step_distance
        self.trend_steps_left -= 1

        if self.distance < D_MIN:
            self.distance = D_MIN
            self._reroll_trend()
            self.trend_direction = 1
        elif self.distance > D_MAX:
            self.distance = D_MAX
            self._reroll_trend()
            self.trend_direction = -1

        return self.distance


def run(ue_count: int, interval: float, log_path: str, gnb_log_path: str,
        verbose: bool = True,
        lock_path: str = DEFAULT_LOCK_PATH,
        lock_timeout: float = DEFAULT_LOCK_TIMEOUT,
        claim_lock: bool = True,
        stale_after: float = DEFAULT_STALE_AFTER):
    ues = [WalkingUE(i, start_distance=random.uniform(D_MIN, D_MAX))
           for i in range(1, ue_count + 1)]

    clock = SlotClock(gnb_log_path)

    with open(log_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "ue_index", "channel_id",
                         "distance_m", "pl_real_dB", "ploss_dB", "lock_wait_s"])

        while True:
            for ue in ues:
                distance = ue.step(interval)
                pl_real = umi_nlos_pathloss(distance)
                ploss = real_to_sim_ploss(pl_real)

                with api_lock(lock_path, timeout=lock_timeout,
                              claim=claim_lock, stale_after=stale_after,
                              verbose=verbose) as waited:
                    channelmod_modify(ue.channel_id, "ploss", f"{ploss:.2f}")

                lock_wait = "" if waited is None else f"{waited:.3f}"

                ts = datetime.now().isoformat()
                writer.writerow([ts, ue.ue_index, ue.channel_id,
                                  f"{distance:.2f}", f"{pl_real:.2f}", f"{ploss:.2f}",
                                  lock_wait])
                f.flush()

                if verbose:
                    print(f"[{ts}] UE{ue.ue_index} (ch{ue.channel_id}): "
                          f"dist={distance:6.1f}m  PL_real={pl_real:5.1f}dB  ploss_sim={ploss:5.2f}dB")

            clock.wait_sim_seconds(interval)


def main():
    parser = argparse.ArgumentParser(description="Urban UE mobility simulation (ploss)")
    parser.add_argument("--ues", type=int, default=2)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--log", type=str, default="/home/mitlab-ai-edge-server/scripts/city_mobility_log.csv")
    parser.add_argument("--gnb-log", type=str, default="/tmp/gnb_log.txt",
                         help="Live gNB log (produced by RANalyzer.py) used for pace synchronisation")
    parser.add_argument("--lock-file", type=str, default=DEFAULT_LOCK_PATH,
                         help="Lock file for the shared API (telnet/channelmod)")
    parser.add_argument("--lock-timeout", type=float, default=DEFAULT_LOCK_TIMEOUT,
                         help="Max wall-clock time (s) to wait for the lock; afterwards the call proceeds without it")
    parser.add_argument("--stale-after", type=float, default=DEFAULT_STALE_AFTER,
                         help="A lock with no live owner is removed after this many seconds (0 = never)")
    parser.add_argument("--no-claim-lock", action="store_true",
                         help="Only wait for another process's lock, do not create one "
                              "(WARNING: nothing then protects telnet on the background side)")
    args = parser.parse_args()

    claim_lock = not args.no_claim_lock

    print("=" * 60)
    print(f" Urban mobility simulation: {args.ues} UE")
    print(f" Interval: {args.interval}s of SIMULATED time | Range: {D_MIN}-{D_MAX}m")
    print(f" CSV log: {args.log}")
    print(f" Synchronisation: {args.gnb_log}")
    print(f" API lock: {args.lock_file} "
          f"({'claiming own' if claim_lock else 'waiting only'}, "
          f"timeout {args.lock_timeout}s)")
    print(" Ctrl+C = stop")
    print("=" * 60)

    try:
        run(args.ues, args.interval, args.log, args.gnb_log,
            lock_path=args.lock_file,
            lock_timeout=args.lock_timeout,
            claim_lock=claim_lock,
            stale_after=args.stale_after)
    except KeyboardInterrupt:
        print("\nStopped.")
        sys.exit(0)


if __name__ == "__main__":
    main()