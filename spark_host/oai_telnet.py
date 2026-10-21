#!/usr/bin/env python3

import socket
import time

HOST = "127.0.0.1"
PORT = 9090
PROMPT = b"softmodem_gnb>"
TIMEOUT = 5.0


def send_command(cmd: str, host: str = HOST, port: int = PORT) -> str:
    with socket.create_connection((host, port), timeout=TIMEOUT) as sock:
        sock.settimeout(TIMEOUT)
        buf = b""

        deadline = time.time() + TIMEOUT
        while PROMPT not in buf and time.time() < deadline:
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
            except socket.timeout:
                break

        sock.sendall(cmd.encode() + b"\r\n")

        response = b""
        deadline = time.time() + TIMEOUT
        while time.time() < deadline:
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk
                if PROMPT in response:
                    break
            except socket.timeout:
                break

        try:
            sock.sendall(b"exit\r\n")
        except OSError:
            pass

        return response.decode(errors="replace")


def channelmod_modify(channel_id: int, param: str, value) -> str:
    return send_command(f"channelmod modify {channel_id} {param} {value}")


def channelmod_show_current() -> str:
    return send_command("channelmod show current")


if __name__ == "__main__":
    print(channelmod_show_current())