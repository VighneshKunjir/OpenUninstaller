"""Running a program's own uninstaller and waiting until it has really finished."""

from __future__ import annotations

import fnmatch
import os
import subprocess
import time
from typing import Callable

import psutil

from .programs import Program, uninstall_command

# Names used by uninstallers that copy themselves to %TEMP% and relaunch (Inno, NSIS, InstallShield...)
HANDOFF_PATTERNS = ["_iu*.tmp", "au_.exe", "un_a.exe", "un.exe", "unins*.exe", "*.tmp", "_is*.exe",
                    "setup.exe", "msiexec.exe", "uninstall*.exe", "uninst*.exe", "idriver.exe", "isbew64.exe"]


def _start(cmd: str) -> subprocess.Popen:
    # A plain string goes straight to CreateProcess, which copes with unquoted "C:\Program Files\..." paths.
    try:
        return subprocess.Popen(cmd)
    except OSError:
        return subprocess.Popen(cmd, shell=True)


def run_uninstaller(p: Program, quiet: bool = False, forced_msi: bool = False,
                    progress: Callable[[str], None] = lambda s: None,
                    cancelled: Callable[[], bool] = lambda: False,
                    timeout: float = 3 * 3600) -> dict:
    """Launch the uninstaller and block until it and every process it spawned have exited."""
    cmd = uninstall_command(p, quiet=quiet, forced_msi=forced_msi)
    if not cmd:
        return {"ran": False, "error": "This program has no built-in uninstaller.", "command": ""}
    progress(f"Running: {cmd}")
    started = time.time()
    try:
        proc = _start(cmd)
    except OSError as e:
        return {"ran": False, "error": str(e), "command": cmd}
    exit_code = wait_tree(proc.pid, started, progress, cancelled, timeout)
    if exit_code is None:
        try:
            exit_code = proc.wait(timeout=0)
        except subprocess.TimeoutExpired:
            pass
    return {"ran": True, "command": cmd, "exit_code": exit_code, "still_installed": p.still_installed(),
            "seconds": round(time.time() - started, 1)}


def wait_tree(root_pid: int, started: float, progress, cancelled, timeout: float) -> int | None:
    tracked: dict[int, psutil.Process] = {}
    try:
        tracked[root_pid] = psutil.Process(root_pid)
    except psutil.Error:
        return None
    me = os.getpid()
    last_label = ""
    while time.time() - started < timeout:
        if cancelled():
            return None
        # Follow children, grandchildren, and anything relaunched by a tracked process.
        for proc in list(tracked.values()):
            try:
                for ch in proc.children(recursive=True):
                    tracked.setdefault(ch.pid, ch)
            except psutil.Error:
                pass
        alive = {pid: pr for pid, pr in tracked.items() if _alive(pr)}
        if not alive:
            # Hand-off check: an uninstaller stub may already have spawned a temp copy and exited
            # before we saw it. Look for fresh processes with typical uninstaller names.
            orphan = _find_handoff(started, me)
            if orphan is None:
                return None
            tracked[orphan.pid] = orphan
            continue
        label = ", ".join(sorted({_name(pr) for pr in alive.values()}))
        if label != last_label:
            progress(f"Waiting for: {label}")
            last_label = label
        time.sleep(0.4)
    return None


def _alive(pr: psutil.Process) -> bool:
    try:
        return pr.is_running() and pr.status() != psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False


def _name(pr: psutil.Process) -> str:
    try:
        return pr.name()
    except psutil.Error:
        return "?"


def _find_handoff(since: float, me: int) -> psutil.Process | None:
    for pr in psutil.process_iter(["name", "create_time", "pid"]):
        try:
            if pr.pid == me or pr.info["create_time"] < since - 1:
                continue
            name = (pr.info["name"] or "").lower()
            if name == "msiexec.exe":
                # The Windows Installer service process is always running; only client copies count.
                if pr.parent() and pr.parent().name().lower() == "services.exe":
                    continue
            if any(fnmatch.fnmatch(name, pat) for pat in HANDOFF_PATTERNS):
                return pr
        except psutil.Error:
            continue
    return None


def kill_process_tree(pid: int) -> None:
    try:
        parent = psutil.Process(pid)
        for ch in parent.children(recursive=True):
            ch.kill()
        parent.kill()
    except psutil.Error:
        pass
