#!/usr/bin/env python3

import argparse
import csv
import os
import time
from contextlib import contextmanager
from datetime import datetime

from oai_telnet import channelmod_modify
from slot_clock import SlotClock

DEFAULT_NOISE_UP = [-90, -75, -65, -60, -55, -50]
DEFAULT_NOISE_DOWN = [-50, -55, -60, -65, -75, -90]
BASELINE_NOISE = -105

DEFAULT_LOCK_PATH = "/tmp/sbx_iface_API.lock"
DEFAULT_LOCK_TIMEOUT = 30.0
LOCK_POLL_INTERVAL = 0.1


def wait_for_unlock(lock_path: str = DEFAULT_LOCK_PATH,
                    poll: float = LOCK_POLL_INTERVAL,
                    timeout: float = DEFAULT_LOCK_TIMEOUT,
                    verbose: bool = True) -> float:
    if not os.path.exists(lock_path):
        return 0.0

    start = time.monotonic()
    if verbose:
        print(f"[lock] waiting for {lock_path} to be released ...")

    while os.path.exists(lock_path):
        waited = time.monotonic() - start
        if waited > timeout:
            print(f"[lock] WARNING: {lock_path} still present after {waited:.1f} s "
                  f"- continuing despite the lock (possibly a stale lock)")
            return waited
        time.sleep(poll)

    waited = time.monotonic() - start
    if verbose:
        print(f"[lock] released after {waited:.2f} s")
    return waited


@contextmanager
def api_lock(lock_path: str = DEFAULT_LOCK_PATH,
             poll: float = LOCK_POLL_INTERVAL,
             timeout: float = DEFAULT_LOCK_TIMEOUT,
             verbose: bool = True):
    start = time.monotonic()
    fd = None
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            waited = time.monotonic() - start
            if waited > timeout:
                raise TimeoutError(
                    f"lock {lock_path} was not released within {timeout} s")
            time.sleep(poll)

    waited = time.monotonic() - start
    if verbose and waited > 0:
        print(f"[lock] acquired after {waited:.2f} s (pid {os.getpid()})")

    try:
        os.write(fd, f"{os.getpid()}\n".encode())
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


def run(channel_id: int, gnb_log_path: str, log_writer=None, step_delay: float = 8.0,
        verbose: bool = True, noise_up=None, noise_down=None,
        lock_path: str = DEFAULT_LOCK_PATH, lock_timeout: float = DEFAULT_LOCK_TIMEOUT,
        claim_lock: bool = False, settle_delay: float = 2.0):
    clock = SlotClock(gnb_log_path)

    up = DEFAULT_NOISE_UP if noise_up is None else noise_up
    down = DEFAULT_NOISE_DOWN if noise_down is None else noise_down

    def log_event(event: str, value):
        ts = datetime.now().isoformat()
        if verbose:
            print(f"[{ts}] UE ch{channel_id}: {event} = {value}")
        if log_writer:
            log_writer.writerow([ts, channel_id, event, value])

    def set_noise(value):
        if claim_lock:
            with api_lock(lock_path, timeout=lock_timeout, verbose=verbose) as waited:
                if waited > 0:
                    log_event("lock_wait_s", round(waited, 3))
                channelmod_modify(channel_id, "noise_power_dB", value)
        else:
            waited = wait_for_unlock(lock_path, timeout=lock_timeout, verbose=verbose)
            if waited > 0:
                log_event("lock_wait_s", round(waited, 3))
            channelmod_modify(channel_id, "noise_power_dB", value)
        log_event("noise_power_dB", value)

    if verbose:
        print("=" * 60)
        print(f" CATASTROPHE: channel {channel_id} - noise injection sequence")
        print("=" * 60)

    set_noise(BASELINE_NOISE)
    clock.wait_sim_seconds(2)

    for noise in up:
        set_noise(noise)
        clock.wait_sim_seconds(step_delay)

    for noise in down:
        set_noise(noise)
        clock.wait_sim_seconds(step_delay)

    set_noise(BASELINE_NOISE)
    if settle_delay > 0:
        clock.wait_sim_seconds(settle_delay)

    if verbose:
        print(f"\nChannel {channel_id}: noise reset to {BASELINE_NOISE} dBm.")
        print("=== SEQUENCE COMPLETED ===")


def main():
    parser = argparse.ArgumentParser(description="Controlled AI-RAN interference (per UE)")
    parser.add_argument("--channel-id", type=int, required=True,
                         help="Channel ID (0=ue1, 1=ue2, 2=ue3, ...)")
    parser.add_argument("--step-delay", type=float, default=8.0,
                         help="Seconds of SIMULATED time per noise step")
    parser.add_argument("--settle-delay", type=float, default=2.0,
                         help="Seconds of SIMULATED time after returning to baseline (recovery phase)")
    parser.add_argument("--log", type=str, default=None,
                         help="Path to the CSV event log (optional)")
    parser.add_argument("--log-append", action="store_true",
                         help="Append to the log file instead of overwriting it (useful in scenario_runner)")
    parser.add_argument("--gnb-log", type=str, default="/tmp/gnb_log.txt",
                         help="Live gNB log (produced by RANalyzer.py) used for pace synchronisation")
    parser.add_argument("--lock-file", type=str, default=DEFAULT_LOCK_PATH,
                         help="Lock file for the shared API - wait until it disappears")
    parser.add_argument("--lock-timeout", type=float, default=DEFAULT_LOCK_TIMEOUT,
                         help="Max wall-clock time (s) to wait for the lock to be released")
    parser.add_argument("--claim-lock", action="store_true",
                         help="Also create an own lock for the duration of the API call "
                              "(only if the background process follows the same O_EXCL convention)")
    args = parser.parse_args()

    log_file = None
    log_writer = None
    if args.log:
        mode = "a" if args.log_append else "w"
        write_header = not (args.log_append and os.path.exists(args.log)
                            and os.path.getsize(args.log) > 0)
        log_file = open(args.log, mode, newline="")
        log_writer = csv.writer(log_file)
        if write_header:
            log_writer.writerow(["timestamp", "channel_id", "event", "value"])

    try:
        run(args.channel_id, args.gnb_log,
            log_writer=log_writer,
            step_delay=args.step_delay,
            settle_delay=args.settle_delay,
            lock_path=args.lock_file,
            lock_timeout=args.lock_timeout,
            claim_lock=args.claim_lock)
    finally:
        if log_file:
            log_file.close()


if __name__ == "__main__":
    main()