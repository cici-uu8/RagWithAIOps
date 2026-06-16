"""Manage local MCP service processes for development.

The Makefile runs in non-interactive command runners during acceptance checks.
Plain ``nohup ... &`` can leave the child tied to that runner's process group,
so this helper starts MCP servers in a new session and uses PID + TCP checks for
status instead of a bare HTTP GET to the streamable-http endpoint.
"""

from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path


def _read_pid(pid_file: Path) -> int | None:
    try:
        return int(pid_file.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return None


def _pid_running(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _tcp_open(host: str, port: int, timeout: float = 0.2) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _wait_for_ready(pid: int, host: str, port: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_running(pid):
            return False
        if _tcp_open(host, port):
            return True
        time.sleep(0.1)
    return False


def _tail(path: Path, max_lines: int = 20) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return ""
    return "\n".join(lines[-max_lines:])


def start(args: argparse.Namespace) -> int:
    pid_file = Path(args.pid_file)
    log_file = Path(args.log_file)
    pid = _read_pid(pid_file)

    if _pid_running(pid):
        if _tcp_open(args.host, args.port):
            print(f"✅ {args.name} MCP 服务已经在运行中")
            print(f"   PID: {pid}")
            print(f"   URL: http://{args.host}:{args.port}/mcp")
            return 0
        print(f"⚠️  {args.name} MCP 进程存在但端口未就绪 (PID: {pid})")
        return 1

    if pid is not None:
        print(f"⚠️  清理 stale pid 文件: {pid_file} (PID: {pid})")
        pid_file.unlink(missing_ok=True)

    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("wb") as log_handle:
        proc = subprocess.Popen(
            [args.python, args.script],
            cwd=args.cwd,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            close_fds=True,
            start_new_session=True,
        )

    pid_file.write_text(f"{proc.pid}\n", encoding="utf-8")
    if _wait_for_ready(proc.pid, args.host, args.port, args.timeout):
        print(f"✅ {args.name} MCP 服务启动成功")
        print(f"   PID: {proc.pid}")
        print(f"   URL: http://{args.host}:{args.port}/mcp")
        print(f"   日志: {log_file}")
        return 0

    print(f"❌ {args.name} MCP 服务启动失败")
    print(f"   PID: {proc.pid}")
    print(f"   日志: {log_file}")
    tail = _tail(log_file)
    if tail:
        print("   最近日志:")
        print(tail)
    if not _pid_running(proc.pid):
        pid_file.unlink(missing_ok=True)
    return 1


def stop(args: argparse.Namespace) -> int:
    pid_file = Path(args.pid_file)
    pid = _read_pid(pid_file)
    if not _pid_running(pid):
        if pid is None:
            print(f"⚠️  未找到 {args.name} MCP pid 文件")
        else:
            print(f"⚠️  {args.name} MCP 进程不存在 (PID: {pid})")
        pid_file.unlink(missing_ok=True)
        return 0

    assert pid is not None
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except PermissionError:
        os.kill(pid, signal.SIGTERM)

    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        if not _pid_running(pid):
            break
        time.sleep(0.1)

    if _pid_running(pid):
        print(f"⚠️  {args.name} MCP 进程仍在运行 (PID: {pid})")
        return 1

    pid_file.unlink(missing_ok=True)
    print(f"✅ {args.name} MCP 服务已停止 (PID: {pid})")
    return 0


def status(args: argparse.Namespace) -> int:
    pid = _read_pid(Path(args.pid_file))
    running = _pid_running(pid)
    tcp_ready = _tcp_open(args.host, args.port)

    print(f"{args.name} MCP 服务:")
    if running:
        print("  状态: 运行中")
        print(f"  PID: {pid}")
    elif pid is not None:
        print("  状态: 未运行")
        print(f"  stale PID: {pid}")
    else:
        print("  状态: 未运行")
    print(f"  URL: http://{args.host}:{args.port}/mcp")
    print(f"  端口: {'✅ 正常' if tcp_ready else '❌ 未监听'}")
    return 0 if running and tcp_ready else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage local MCP service processes")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("start", "stop", "status"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--name", required=True)
        subparser.add_argument("--pid-file", required=True)
        subparser.add_argument("--host", default="127.0.0.1")
        subparser.add_argument("--port", required=True, type=int)
        subparser.add_argument("--timeout", default=5.0, type=float)
        if command == "start":
            subparser.add_argument("--script", required=True)
            subparser.add_argument("--log-file", required=True)
            subparser.add_argument("--python", default=sys.executable)
            subparser.add_argument("--cwd", default=".")
        if command == "start":
            subparser.set_defaults(func=start)
        elif command == "stop":
            subparser.set_defaults(func=stop)
        else:
            subparser.set_defaults(func=status)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
