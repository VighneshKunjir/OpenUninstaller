"""Deleting leftovers safely, the Backup Manager, restore points and the Uninstall History."""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import shutil
import uuid
import winreg
from dataclasses import asdict
from typing import Callable, Iterable

import psutil

from . import winutil as wu
from .config import DATA_DIR, settings
from .leftovers import Leftover, is_excluded_key, is_protected_path

BACKUP_DIR = os.path.join(DATA_DIR, "Backups")
HISTORY_DIR = os.path.join(DATA_DIR, "History")


def _now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- restore point / full registry backup

def create_restore_point(description: str) -> tuple[bool, str]:
    """Ask Windows for a System Restore point. Temporarily lifts the once-per-24h throttle."""
    if not wu.is_admin():
        return False, "Administrator rights are required to create a restore point."
    sub = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\SystemRestore"
    old = wu.get_value(winreg.HKEY_LOCAL_MACHINE, sub, "SystemRestorePointCreationFrequency", wu.VIEW_64)
    try:
        wu.set_value(winreg.HKEY_LOCAL_MACHINE, sub, "SystemRestorePointCreationFrequency",
                     winreg.REG_DWORD, 0, wu.VIEW_64)
    except OSError:
        pass
    desc = description.replace("'", "''")[:200]
    r = wu.powershell(f"Checkpoint-Computer -Description '{desc}' -RestorePointType APPLICATION_UNINSTALL "
                      f"-ErrorAction Stop", timeout=900)
    try:
        if old is None:
            wu.delete_value(winreg.HKEY_LOCAL_MACHINE, sub, "SystemRestorePointCreationFrequency", wu.VIEW_64)
        else:
            wu.set_value(winreg.HKEY_LOCAL_MACHINE, sub, "SystemRestorePointCreationFrequency",
                         winreg.REG_DWORD, old, wu.VIEW_64)
    except OSError:
        pass
    if r.returncode == 0:
        return True, "Restore point created."
    msg = (r.stderr or r.stdout).strip().splitlines()
    return False, (msg[0] if msg else "System Restore is disabled or unavailable.")


def full_registry_backup(progress: Callable[[str], None] = lambda s: None) -> str:
    folder = os.path.join(DATA_DIR, "RegistryBackups", dt.datetime.now().strftime("%Y%m%d-%H%M%S"))
    os.makedirs(folder, exist_ok=True)
    for name, hive, sub in (("HKLM_SOFTWARE", winreg.HKEY_LOCAL_MACHINE, "SOFTWARE"),
                            ("HKCU", winreg.HKEY_CURRENT_USER, ""),
                            ("HKLM_SYSTEM_Services", winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Services")):
        progress(f"Exporting {name}...")
        wu.reg_export(hive, sub, wu.VIEW_64 if hive == winreg.HKEY_LOCAL_MACHINE else 0,
                      os.path.join(folder, name + ".reg"))
    return folder


# ---------------------------------------------------------------- deletion


def _serialize_value(data, vtype):
    if isinstance(data, bytes):
        return {"b64": base64.b64encode(data).decode()}
    return {"v": data}


def _deserialize_value(blob):
    return base64.b64decode(blob["b64"]) if "b64" in blob else blob["v"]


def _kill_processes_under(folder: str) -> list[str]:
    killed = []
    for proc in psutil.process_iter(["exe", "name", "pid"]):
        exe = proc.info.get("exe")
        if exe and wu.is_under(exe, folder) and proc.pid != os.getpid():
            try:
                proc.kill()
                killed.append(proc.info["name"])
            except psutil.Error:
                pass
    return killed


def _remove_fs(path: str, mode: str, files_dir: str) -> tuple[str, str]:
    """Returns (status, detail). status: deleted | recycled | backed_up | reboot | failed."""
    try:
        if mode == "recycle":
            from send2trash import send2trash
            send2trash(path)
            return "recycled", ""
        if mode == "backup":
            drive, rest = os.path.splitdrive(os.path.abspath(path))
            dest = os.path.join(files_dir, drive.rstrip(":"), rest.lstrip("\\"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.move(path, dest)
            return "backed_up", dest
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
        return "deleted", ""
    except Exception as e:
        err = str(e)
    # Some files are locked; delete what we can and schedule the rest for the next boot.
    pending = 0
    if os.path.isdir(path):
        for root, dirs, files in reversed(list(wu.safe_walk(path))):
            for f in files:
                fp = os.path.join(root, f)
                try:
                    os.remove(fp)
                except OSError:
                    pending += wu.delete_on_reboot(fp)
            for d in dirs:
                dp = os.path.join(root, d)
                try:
                    os.rmdir(dp)
                except OSError:
                    pending += wu.delete_on_reboot(dp)
        try:
            os.rmdir(path)
            return "deleted", ""
        except OSError:
            pending += wu.delete_on_reboot(path)
    elif os.path.exists(path):
        pending += wu.delete_on_reboot(path)
    if pending:
        return "reboot", "Locked - will be removed at next restart"
    return ("deleted", "") if not os.path.exists(path) else ("failed", err)


def delete_items(items: Iterable[Leftover], operation: str, program: str,
                 progress: Callable[[str], None] = lambda s: None,
                 file_mode: str | None = None, backup_registry: bool | None = None) -> dict:
    """Delete the given leftovers, backing up first. Returns the backup manifest (also saved to disk)."""
    file_mode = file_mode or settings["file_delete_mode"]
    backup_registry = settings["backup_registry_items"] if backup_registry is None else backup_registry
    items = [i for i in items if not i.excluded]
    bid = dt.datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    folder = os.path.join(BACKUP_DIR, bid)
    reg_dir = os.path.join(folder, "reg")
    files_dir = os.path.join(folder, "files")
    os.makedirs(reg_dir, exist_ok=True)
    manifest = {"id": bid, "created": _now(), "operation": operation, "program": program,
                "file_mode": file_mode, "items": []}

    def record(it: Leftover, status: str, detail: str = "", **extra):
        manifest["items"].append({"kind": it.kind, "path": it.path, "value_name": it.value_name,
                                  "hive": it.hive, "sub": it.sub, "view": it.view, "reason": it.reason,
                                  "status": status, "detail": detail, **extra})

    order = {"service": 0, "task": 1, "regvalue": 2, "regkey": 3, "file": 4, "folder": 5}
    items.sort(key=lambda i: (order.get(i.kind, 9), -len(i.sub or i.path)))
    deleted_keys: list[str] = []
    n = 0
    for it in items:
        n += 1
        progress(f"[{n}/{len(items)}] {it.path}" + (f" -> {it.value_name}" if it.value_name else ""))
        try:
            if it.kind == "service":
                reg_file = os.path.join(reg_dir, f"{n:04d}.reg")
                wu.reg_export(it.hive, it.sub, 0, reg_file)
                wu.run_hidden(["sc.exe", "stop", it.path], timeout=60)
                r = wu.run_hidden(["sc.exe", "delete", it.path], timeout=60)
                ok = r.returncode == 0 or not wu.key_exists(it.hive, it.sub)
                record(it, "deleted" if ok else "failed", "" if ok else r.stdout.strip()[-200:], reg_file=reg_file)
            elif it.kind == "task":
                xml_file = os.path.join(reg_dir, f"{n:04d}.task.xml")
                q = wu.run_hidden(["schtasks.exe", "/query", "/tn", it.path, "/xml"], timeout=60)
                if q.returncode == 0:
                    with open(xml_file, "w", encoding="utf-16") as f:
                        f.write(q.stdout)
                r = wu.run_hidden(["schtasks.exe", "/delete", "/tn", it.path, "/f"], timeout=60)
                ok = r.returncode == 0
                record(it, "deleted" if ok else "failed", "" if ok else (r.stderr or r.stdout).strip()[-200:],
                       task_xml=xml_file if q.returncode == 0 else None)
            elif it.kind == "regvalue":
                if any(it.path.lower().startswith(k) for k in deleted_keys):
                    record(it, "deleted", "Removed with its parent key")
                    continue
                with wu.open_key(it.hive, it.sub, it.view) as k:
                    data, vtype = winreg.QueryValueEx(k, it.value_name or "")
                wu.delete_value(it.hive, it.sub, it.value_name or "", it.view)
                record(it, "deleted", value_type=vtype, value=_serialize_value(data, vtype))
            elif it.kind == "regkey":
                if is_excluded_key(it.path):
                    record(it, "skipped", "Excluded key")
                    continue
                low = it.path.lower() + "\\"
                if any(low.startswith(k) for k in deleted_keys):
                    record(it, "deleted", "Removed with its parent key")
                    continue
                reg_file = None
                if backup_registry:
                    reg_file = os.path.join(reg_dir, f"{n:04d}.reg")
                    if not wu.reg_export(it.hive, it.sub, it.view, reg_file):
                        reg_file = None
                wu.delete_key_tree(it.hive, it.sub, it.view)
                deleted_keys.append(low)
                record(it, "deleted", reg_file=reg_file)
            elif it.kind in ("file", "folder"):
                if is_protected_path(it.path):
                    record(it, "skipped", "Protected location")
                    continue
                if not settings["include_cloud_folders"] and wu.is_cloud_path(it.path):
                    record(it, "skipped", "Phone/cloud storage (excluded in Options)")
                    continue
                if not os.path.lexists(it.path):
                    record(it, "deleted", "Already gone")
                    continue
                if it.kind == "folder" and settings["kill_running_exes"]:
                    _kill_processes_under(it.path)
                status, detail = _remove_fs(it.path, file_mode, files_dir)
                record(it, status, detail)
        except FileNotFoundError:
            record(it, "deleted", "Already gone")
        except Exception as e:
            record(it, "failed", str(e))
    with open(os.path.join(folder, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, default=str)
    return manifest


# ---------------------------------------------------------------- backup manager


def list_backups() -> list[dict]:
    out = []
    if not os.path.isdir(BACKUP_DIR):
        return out
    for bid in os.listdir(BACKUP_DIR):
        mf = os.path.join(BACKUP_DIR, bid, "manifest.json")
        try:
            with open(mf, encoding="utf-8") as f:
                m = json.load(f)
        except (OSError, ValueError):
            continue
        m["size"] = wu.dir_size(os.path.join(BACKUP_DIR, bid))
        m["count"] = sum(1 for i in m["items"] if i.get("reg_file") or i.get("value") or i.get("task_xml")
                         or i.get("status") == "backed_up")
        out.append(m)
    out.sort(key=lambda m: m["created"], reverse=True)
    return out


def restorable(item: dict) -> bool:
    return bool(item.get("reg_file") or "value" in item or item.get("task_xml") or item.get("status") == "backed_up")


def restore_backup(bid: str, indexes: Iterable[int] | None = None,
                   progress: Callable[[str], None] = lambda s: None) -> list[tuple[str, bool, str]]:
    with open(os.path.join(BACKUP_DIR, bid, "manifest.json"), encoding="utf-8") as f:
        m = json.load(f)
    wanted = set(indexes) if indexes is not None else None
    results = []
    # Keys before values so a value lands in a restored key; files last.
    order = {"regkey": 0, "service": 0, "regvalue": 1, "task": 2, "file": 3, "folder": 3}
    entries = sorted(enumerate(m["items"]), key=lambda e: order.get(e[1]["kind"], 9))
    for idx, it in entries:
        if (wanted is not None and idx not in wanted) or not restorable(it):
            continue
        progress(f"Restoring {it['path']}")
        try:
            if it.get("reg_file"):
                ok = wu.reg_import(it["reg_file"], it.get("view") or 0)
                results.append((it["path"], ok, "" if ok else "reg import failed"))
            elif "value" in it:
                wu.set_value(it["hive"], it["sub"], it.get("value_name") or "", it["value_type"],
                             _deserialize_value(it["value"]), it.get("view") or 0)
                results.append((it["path"] + " -> " + (it.get("value_name") or "(Default)"), True, ""))
            elif it.get("task_xml"):
                r = wu.run_hidden(["schtasks.exe", "/create", "/tn", it["path"], "/xml", it["task_xml"], "/f"])
                results.append((it["path"], r.returncode == 0, (r.stderr or "").strip()))
            elif it.get("status") == "backed_up":
                os.makedirs(os.path.dirname(it["path"]), exist_ok=True)
                shutil.move(it["detail"], it["path"])
                results.append((it["path"], True, ""))
        except Exception as e:
            results.append((it["path"], False, str(e)))
    return results


def delete_backup(bid: str) -> None:
    path = os.path.join(BACKUP_DIR, bid)
    try:
        from send2trash import send2trash
        send2trash(path)
    except Exception:
        shutil.rmtree(path, ignore_errors=True)


def delete_backups_before(date: dt.date) -> int:
    n = 0
    for m in list_backups():
        if dt.datetime.strptime(m["created"][:10], "%Y-%m-%d").date() < date:
            delete_backup(m["id"])
            n += 1
    return n


# ---------------------------------------------------------------- uninstall history


def add_history(program: dict, operation: str, mode: str | None, manifest: dict | None, notes: str = "") -> str:
    os.makedirs(HISTORY_DIR, exist_ok=True)
    hid = dt.datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    items = (manifest or {}).get("items", [])
    rec = {
        "id": hid, "date": _now(), "operation": operation, "scan_mode": mode, "program": program,
        "backup_id": (manifest or {}).get("id"), "notes": notes,
        "ok": sum(1 for i in items if i["status"] in ("deleted", "recycled", "backed_up", "reboot")),
        "failed": sum(1 for i in items if i["status"] == "failed"),
        "items": [{k: i.get(k) for k in ("kind", "path", "value_name", "status", "detail")} for i in items],
    }
    with open(os.path.join(HISTORY_DIR, hid + ".json"), "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=2, default=str)
    return hid


def list_history() -> list[dict]:
    out = []
    if os.path.isdir(HISTORY_DIR):
        for fn in os.listdir(HISTORY_DIR):
            try:
                with open(os.path.join(HISTORY_DIR, fn), encoding="utf-8") as f:
                    out.append(json.load(f))
            except (OSError, ValueError):
                pass
    out.sort(key=lambda r: r["date"], reverse=True)
    return out


def delete_history(hid: str | None = None) -> None:
    if hid is None:
        shutil.rmtree(HISTORY_DIR, ignore_errors=True)
    else:
        try:
            os.remove(os.path.join(HISTORY_DIR, hid + ".json"))
        except OSError:
            pass


def export_history(rec: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        p = rec.get("program") or {}
        f.write(f"{rec['operation']} - {p.get('name', '')} {p.get('version', '')}\n{rec['date']}\n\n")
        for i in rec["items"]:
            f.write(f"[{i['status']:>9}] {i['kind']:<8} {i['path']}"
                    + (f" -> {i['value_name']}" if i.get("value_name") is not None else "")
                    + (f"  ({i['detail']})" if i.get("detail") else "") + "\n")


def leftover_to_dict(it: Leftover) -> dict:
    return asdict(it)
