#!/usr/bin/env python3

import argparse
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

COMPOSE_PATH = "/home/mitlab-ai-edge-server/Documents/oai/openairinterface5g/cmake_targets/ran_build2/build/oai-multi-ue/docker-compose.yml"
IPERF_SERVER_LIST_FILE = Path(__file__).parent / "iperf3_server_list.txt"
IPERF_LOG_DIR = Path(__file__).parent / "iperf_logs"

CHECK_INTERVAL = 5
NO_TRAFFIC_TIMEOUT = 120
TUNNEL_MISSING_THRESHOLD = 15
RESTART_WAIT = 30
WAITING_LOG_EVERY = 6


def run(cmd, timeout=15):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def container_exists(idx: int) -> bool:
    r = run(["docker", "inspect", f"oai-ue{idx}"])
    return r.returncode == 0


def get_ip(idx: int) -> str:
    r = run(["docker", "exec", f"oai-ue{idx}", "ip", "-4", "addr", "show", "dev", "oaitun_ue1"])
    for line in r.stdout.splitlines():
        line = line.strip()
        if line.startswith("inet "):
            return line.split()[1].split("/")[0]
    return ""


def get_bytes(idx: int, direction: str) -> int:
    r = run(["docker", "exec", f"oai-ue{idx}", "cat",
             f"/sys/class/net/oaitun_ue1/statistics/{direction}_bytes"])
    try:
        return int(r.stdout.strip())
    except ValueError:
        return -1


def tunnel_exists(idx: int) -> bool:
    r = run(["docker", "exec", f"oai-ue{idx}", "ip", "link", "show", "oaitun_ue1"])
    return r.returncode == 0


def restart_container(idx: int, reason: str):
    print(f"\n{'='*50}\nRESTART UE{idx}\nReason: {reason}\n{'='*50}")
    run(["docker", "restart", f"oai-ue{idx}"], timeout=30)
    print(f"UE{idx}: container restarted, waiting {RESTART_WAIT}s...")
    time.sleep(RESTART_WAIT)


def pick_iperf_target():
    if not IPERF_SERVER_LIST_FILE.exists():
        return None, None
    lines = [l.strip() for l in IPERF_SERVER_LIST_FILE.read_text().splitlines() if l.strip()]
    if not lines:
        return None, None
    line = random.choice(lines)
    host, port_raw = line.split(";")
    port = port_raw.split("-")[0]
    return host, port


def run_iperf(idx: int, stop_event: threading.Event):
    IPERF_LOG_DIR.mkdir(exist_ok=True)
    log_path = IPERF_LOG_DIR / f"ue{idx}.log"
    while not stop_event.is_set():
        if not container_exists(idx):
            time.sleep(2)
            continue
        ip = get_ip(idx)
        if not ip:
            time.sleep(2)
            continue
        host, port = pick_iperf_target()
        if not host:
            time.sleep(5)
            continue
        print(f"UE{idx} (IP: {ip}) -> iperf3 {host}:{port}")
        try:
            with open(log_path, "a") as f:
                subprocess.run(
                    ["docker", "exec", f"oai-ue{idx}", "iperf3", "-c", host, "-p", port,
                     "-R", "-B", ip, "-b", "20M", "-t", "30",
                     "--connect-timeout", "3000"],
                    stdout=f, stderr=subprocess.STDOUT, timeout=40
                )
        except subprocess.TimeoutExpired:
            print(f"UE{idx}: iperf3 timed out (server unresponsive), switching target.")
        except Exception as e:
            print(f"UE{idx}: iperf3 error ({e}), switching target.")
        print(f"UE{idx}: iperf3 session ended.")
        time.sleep(2)


def monitor(idx: int, stop_event: threading.Event):
    print(f"Monitor for UE{idx} started.")
    last_rx, last_tx = 0, 0
    last_traffic_ts = time.time()
    tunnel_missing_count = 0
    known_ip = ""
    ever_connected = False
    waiting_cycles = 0

    while not stop_event.is_set():
        if not container_exists(idx):
            print(f"UE{idx}: container missing.")
            run(["docker", "compose", "-f", COMPOSE_PATH, "up", f"ue{idx}", "-d"], timeout=30)
            time.sleep(RESTART_WAIT)
            continue

        if not tunnel_exists(idx):
            if not ever_connected:
                waiting_cycles += 1
                if waiting_cycles % WAITING_LOG_EVERY == 1:
                    print(f"UE{idx}: waiting for initial connection...")
                time.sleep(CHECK_INTERVAL)
                continue
            tunnel_missing_count += 1
            print(f"UE{idx}: tunnel missing ({tunnel_missing_count}/{TUNNEL_MISSING_THRESHOLD})")
            if tunnel_missing_count >= TUNNEL_MISSING_THRESHOLD:
                tunnel_missing_count = 0
                restart_container(idx, "oaitun_ue1 interface missing (persisted)")
                known_ip = ""
                ever_connected = False
                waiting_cycles = 0
            time.sleep(CHECK_INTERVAL)
            continue
        else:
            tunnel_missing_count = 0
            ever_connected = True

        current_ip = get_ip(idx)

        if not current_ip:
            time.sleep(CHECK_INTERVAL)
            continue

        if current_ip != known_ip:
            print(f"UE{idx}: detected IP {current_ip}"
                  + (f" (previously {known_ip})" if known_ip else ""))
            known_ip = current_ip
            last_rx = get_bytes(idx, "rx")
            last_tx = get_bytes(idx, "tx")
            last_traffic_ts = time.time()
            time.sleep(CHECK_INTERVAL)
            continue

        current_rx = get_bytes(idx, "rx")
        current_tx = get_bytes(idx, "tx")

        if current_rx < 0 or current_tx < 0:
            print(f"UE{idx}: unable to read RX/TX counters.")
            time.sleep(CHECK_INTERVAL)
            continue

        rx_diff = max(0, current_rx - last_rx)
        tx_diff = max(0, current_tx - last_tx)

        if rx_diff > 0 or tx_diff > 0:
            last_traffic_ts = time.time()
            print(f"UE{idx} | IP={known_ip} | RX +{rx_diff} B | TX +{tx_diff} B")
        else:
            idle_time = int(time.time() - last_traffic_ts)
            print(f"UE{idx} | no traffic | idle {idle_time}s")
            if idle_time >= NO_TRAFFIC_TIMEOUT:
                print(f"UE{idx}: restarting iperf3 (idle {idle_time}s)")
                last_traffic_ts = time.time()

        last_rx, last_tx = current_rx, current_tx
        time.sleep(CHECK_INTERVAL)


def main():
    parser = argparse.ArgumentParser(description="Multi-UE manager (revised version of ue.sh)")
    parser.add_argument("count", type=int, help="Number of UEs to start and monitor")
    args = parser.parse_args()

    print("=" * 50)
    print(f" OAI Multi-UE manager (Python) - {args.count} UE")
    print("=" * 50)

    print("Shutting down old containers...")
    run(["docker", "compose", "-f", COMPOSE_PATH, "down"], timeout=60)

    for i in range(1, args.count + 1):
        print(f"Starting UE{i}...")
        run(["docker", "compose", "-f", COMPOSE_PATH, "up", f"ue{i}", "-d"], timeout=30)
        time.sleep(5)

    print("Waiting for initial UE connection...")
    time.sleep(10)

    stop_event = threading.Event()
    threads = []
    for i in range(1, args.count + 1):
        t_mon = threading.Thread(target=monitor, args=(i, stop_event), daemon=True)
        t_iperf = threading.Thread(target=run_iperf, args=(i, stop_event), daemon=True)
        t_mon.start()
        t_iperf.start()
        threads.extend([t_mon, t_iperf])

    print("\n" + "=" * 50)
    print(" All UEs started. Monitoring active. Ctrl+C = stop.")
    print("=" * 50)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
        stop_event.set()
        run(["docker", "compose", "-f", COMPOSE_PATH, "down"], timeout=60)
        sys.exit(0)


if __name__ == "__main__":
    main()