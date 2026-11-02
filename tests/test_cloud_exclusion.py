"""Phone/cloud storage exclusion tests (Phone Link, OneDrive, Dropbox...).

Uses whatever sync root this PC has; skips the device-specific checks when there is none.
Every real delete function is replaced by a recorder first - nothing can be deleted.
Run:  .venv\\Scripts\\python tests\\test_cloud_exclusion.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import send2trash  # noqa: E402
from openuninstaller import backup, tools, winutil as wu  # noqa: E402
from openuninstaller.config import settings  # noqa: E402
from openuninstaller.leftovers import Leftover, Target, scan  # noqa: E402

# ---- make every deletion path inert -------------------------------------------------------------
attempted = []
send2trash.send2trash = lambda p: attempted.append(("send2trash", p))
tools.os.remove = lambda p: attempted.append(("os.remove", p))
backup._remove_fs = lambda p, mode, d: (attempted.append(("_remove_fs", p)) or ("deleted", ""))

results = []


def check(label, cond):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + label)


def first_file(root, limit=3000):
    """Any file inside the sync root (listing only)."""
    n = 0
    for d, _dirs, files in wu.safe_walk(root, include_cloud=True):
        for f in files:
            return os.path.join(d, f)
        n += 1
        if n > limit:
            break
    return None


def main():
    saved = settings.data.get("include_cloud_folders")
    try:
        # junctions are never followed (works on every PC)
        tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(tmp, "real"))
        open(os.path.join(tmp, "real", "x.tmp"), "w").close()
        subprocess.run(["cmd", "/c", "mklink", "/J", os.path.join(tmp, "junction"), os.path.join(tmp, "real")],
                       capture_output=True)
        walked = [d for d, _ds, _fs in wu.safe_walk(tmp)]
        check("junction not followed", os.path.join(tmp, "real") in walked
              and os.path.join(tmp, "junction") not in walked)
        os.rmdir(os.path.join(tmp, "junction"))
        shutil.rmtree(tmp, ignore_errors=True)
        check("normal folder is not cloud", not wu.is_cloud_path(os.environ["LOCALAPPDATA"]))

        roots = [r for r, _n in wu.sync_roots() if os.path.isdir(r)]
        if not roots:
            print("SKIP no phone/cloud sync root on this PC - device checks skipped")
            return all(results) and not attempted
        root = max(roots, key=len)                  # the most specific root, e.g. the phone itself
        sample = first_file(root)
        print(f"using sync root: {root}")
        check("sync root detected as cloud", wu.is_cloud_path(root))

        skipped = []
        for d, dirs, _f in wu.safe_walk(os.path.dirname(root), False, lambda p, k: skipped.append((k, p))):
            dirs[:] = []
        check("safe_walk does not enter the sync root", any(k == "cloud" for k, _p in skipped))

        settings.data["include_cloud_folders"] = False
        sk = []
        found = tools.scan_junk([root], skipped=sk)
        check("junk scan (excluded) finds nothing there", not found)
        check("junk scan reports the skipped folder", bool(sk))

        if sample:
            res = tools.delete_files([sample], recycle=False)
            check("junk delete refuses a cloud file", res[0]["status"] == "skipped")
            m = backup.delete_items([Leftover("file", sample, "test")], "test", "test")
            check("leftover delete refuses a cloud file", m["items"][0]["status"] == "skipped")
            shutil.rmtree(os.path.join(backup.BACKUP_DIR, m["id"]), ignore_errors=True)
            done, errs = tools.shred_paths([sample])
            check("shredder refuses a cloud file", done == 0 and bool(errs))
            check("the file still exists", os.path.exists(sample))

        top = os.path.basename(root)
        items = scan(Target.forced(names=[top]), "advanced")
        check("leftover scan (excluded) offers nothing inside cloud storage",
              not any(wu.is_cloud_path(i.path) for i in items if i.kind in ("file", "folder")))
        check("no deletion was attempted", not attempted)
    finally:
        settings.data["include_cloud_folders"] = saved
    print("deletions attempted:", attempted)
    return all(results) and not attempted


if __name__ == "__main__":
    ok = main()
    print("\nALL PASSED" if ok else "\nSOME CHECKS FAILED")
    sys.exit(0 if ok else 1)
