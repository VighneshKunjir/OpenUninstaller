"""Command line interface.

  python -m openuninstaller list [--filter TEXT] [--all]
  python -m openuninstaller scan NAME [--mode safe|moderate|advanced]
  python -m openuninstaller uninstall NAME [--quiet] [--mode M] [--yes] [--no-restore-point]
  python -m openuninstaller forced --name NAME [--path PATH] [--mode M] [--yes]
  python -m openuninstaller backups | restore BACKUP_ID | history
  python -m openuninstaller autoruns
"""

from __future__ import annotations

import argparse
import sys

from . import backup, programs, autorun, winutil as wu
from .leftovers import Target, scan
from .uninstall import run_uninstaller


def _pick(name: str) -> programs.Program:
    matches = programs.find_by_name(name)
    exact = [p for p in matches if p.name.lower() == name.lower()]
    matches = exact or matches
    if not matches:
        sys.exit(f"No installed program matches '{name}'.")
    if len(matches) > 1:
        print("Several programs match:")
        for p in matches:
            print(f"  {p.name} {p.version} ({p.scope})")
        sys.exit("Be more specific.")
    return matches[0]


def _print_items(items):
    for i, it in enumerate(items):
        flag = "X" if it.excluded else ("*" if it.created else " ")
        val = f" -> {it.value_name or '(Default)'}" if it.kind == "regvalue" else ""
        size = f" [{wu.human_size(it.size)}]" if it.size else ""
        print(f"{i:4d} {flag} {it.kind:<8} {it.path}{val}{size}  ({it.reason})")
    print(f"\n{len(items)} items. '*' = created by the program, 'X' = protected (never deleted).")


def _confirm_and_delete(items, operation, program_dict, mode, yes):
    deletable = [i for i in items if i.created and not i.excluded]
    if not deletable:
        print("Nothing to delete.")
        backup.add_history(program_dict, operation, mode, None)
        return
    if not yes:
        ans = input(f"Delete the {len(deletable)} items marked '*'? (registry is backed up) [y/N] ")
        if ans.strip().lower() != "y":
            return
    m = backup.delete_items(deletable, operation, program_dict.get("name", ""), progress=print)
    backup.add_history(program_dict, operation, mode, m)
    ok = sum(1 for i in m["items"] if i["status"] != "failed")
    print(f"Done: {ok} removed, {len(m['items']) - ok} failed. Backup id: {m['id']}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="openuninstaller")
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("list")
    a.add_argument("--filter", default="")
    a.add_argument("--all", action="store_true", help="include system components and updates")
    a = sp.add_parser("scan")
    a.add_argument("name")
    a.add_argument("--mode", default="moderate", choices=["safe", "moderate", "advanced"])
    a = sp.add_parser("uninstall")
    a.add_argument("name")
    a.add_argument("--quiet", action="store_true")
    a.add_argument("--mode", default="moderate", choices=["safe", "moderate", "advanced"])
    a.add_argument("--yes", action="store_true")
    a.add_argument("--no-restore-point", action="store_true")
    a = sp.add_parser("forced")
    a.add_argument("--name", action="append", default=[])
    a.add_argument("--path", action="append", default=[])
    a.add_argument("--mode", default="moderate", choices=["safe", "moderate", "advanced"])
    a.add_argument("--yes", action="store_true")
    sp.add_parser("backups")
    a = sp.add_parser("restore")
    a.add_argument("backup_id")
    sp.add_parser("history")
    sp.add_parser("autoruns")
    args = ap.parse_args(argv)

    if args.cmd == "list":
        for p in programs.list_programs(args.all, args.all):
            if args.filter.lower() in (p.name + p.publisher).lower():
                print(f"{p.name[:50]:<50} {p.version[:16]:<16} {p.publisher[:28]:<28} {p.scope}")
    elif args.cmd == "scan":
        p = _pick(args.name)
        _print_items(scan(Target.from_program(p), args.mode, progress=lambda s: print("..", s, file=sys.stderr)))
    elif args.cmd == "uninstall":
        p = _pick(args.name)
        if not args.no_restore_point:
            print(backup.create_restore_point(f"Before uninstalling {p.name}")[1])
        target = Target.from_program(p)          # captured before the uninstaller removes the info
        res = run_uninstaller(p, quiet=args.quiet, progress=print)
        print(res)
        items = scan(target, args.mode, progress=lambda s: print("..", s, file=sys.stderr))
        _print_items(items)
        _confirm_and_delete(items, "Uninstall", p.to_dict(), args.mode, args.yes)
    elif args.cmd == "forced":
        t = Target.forced(args.name, args.path)
        items = scan(t, args.mode, progress=lambda s: print("..", s, file=sys.stderr))
        _print_items(items)
        _confirm_and_delete(items, "Forced Uninstall", {"name": "; ".join(t.names)}, args.mode, args.yes)
    elif args.cmd == "backups":
        for m in backup.list_backups():
            print(f"{m['id']}  {m['created']}  {m['operation']:<18} {m['program'][:40]:<40} "
                  f"{m['count']} items  {wu.human_size(m['size'])}")
    elif args.cmd == "restore":
        for path, ok, err in backup.restore_backup(args.backup_id, progress=print):
            print(("OK   " if ok else "FAIL ") + path + (f"  {err}" if err else ""))
    elif args.cmd == "history":
        for r in backup.list_history():
            print(f"{r['date']}  {r['operation']:<18} {(r['program'] or {}).get('name', '')[:40]:<40} "
                  f"ok={r['ok']} failed={r['failed']}")
    elif args.cmd == "autoruns":
        for it in autorun.list_autoruns():
            print(f"[{'on ' if it.enabled else 'off'}] {it.kind:<8} {it.name[:40]:<40} {it.location:<22} {it.command[:70]}")


if __name__ == "__main__":
    main()
