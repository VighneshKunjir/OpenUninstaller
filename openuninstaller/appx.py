"""Windows (Store / UWP / MSIX) apps via the Appx PowerShell module."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from . import winutil as wu


@dataclass
class WinApp:
    name: str
    display_name: str
    full_name: str
    family_name: str
    publisher: str
    version: str
    install_location: str
    non_removable: bool
    is_framework: bool
    signature: str
    app_ids: list

    @property
    def data_folder(self) -> str:
        return os.path.join(os.environ.get("LOCALAPPDATA", ""), "Packages", self.family_name)


_LIST_SCRIPT = r"""
$ErrorActionPreference = 'SilentlyContinue'
$all = if ($args -contains 'all') { Get-AppxPackage -AllUsers } else { Get-AppxPackage }
$out = foreach ($p in $all) {
  $disp = $p.Name; $ids = @()
  try {
    $m = Get-AppxPackageManifest -Package $p.PackageFullName
    $d = $m.Package.Properties.DisplayName
    if ($d -and -not $d.StartsWith('ms-resource')) { $disp = $d }
    $ids = @($m.Package.Applications.Application | ForEach-Object { $_.Id })
  } catch {}
  [pscustomobject]@{ Name=$p.Name; Display=$disp; Full=$p.PackageFullName; Family=$p.PackageFamilyName;
    Publisher=$p.Publisher; Version="$($p.Version)"; Location=$p.InstallLocation;
    NonRemovable=[bool]$p.NonRemovable; Framework=[bool]$p.IsFramework; Sig="$($p.SignatureKind)"; Ids=$ids }
}
$out | ConvertTo-Json -Depth 3 -Compress
"""


def _pretty_publisher(pub: str) -> str:
    fields = {}
    for part in (pub or "").split(","):
        key, _, val = part.strip().partition("=")
        fields[key.upper()] = val.strip('"')
    return fields.get("O") or fields.get("CN") or pub


def list_apps(include_system: bool = False, all_users: bool = False) -> list[WinApp]:
    script = _LIST_SCRIPT.replace("$args -contains 'all'", "$true" if all_users else "$false")
    r = wu.powershell(script, timeout=300)
    try:
        data = json.loads(r.stdout or "[]")
    except ValueError:
        return []
    if isinstance(data, dict):
        data = [data]
    apps = []
    for d in data:
        a = WinApp(d["Name"], d.get("Display") or d["Name"], d["Full"], d["Family"], _pretty_publisher(d["Publisher"]),
                   d["Version"], d.get("Location") or "", d["NonRemovable"], d["Framework"], d.get("Sig", ""),
                   d.get("Ids") or [])
        if not include_system and (a.is_framework or a.non_removable or a.signature == "System"):
            continue
        apps.append(a)
    apps.sort(key=lambda a: a.display_name.lower())
    return apps


def _ps_quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def uninstall(app: WinApp, all_users: bool = False) -> tuple[bool, str]:
    extra = " -AllUsers" if all_users else ""
    r = wu.powershell(f"Remove-AppxPackage -Package {_ps_quote(app.full_name)}{extra} -ErrorAction Stop", timeout=900)
    if r.returncode != 0 and all_users:
        # Also drop the provisioned copy so it is not reinstalled for new accounts
        wu.powershell(f"Get-AppxProvisionedPackage -Online | Where-Object DisplayName -eq {_ps_quote(app.name)} | "
                      f"Remove-AppxProvisionedPackage -Online", timeout=900)
    return r.returncode == 0, (r.stderr or "").strip()


def reset(app: WinApp) -> tuple[bool, str]:
    r = wu.powershell(f"Get-AppxPackage -Name {_ps_quote(app.name)} | Reset-AppxPackage -ErrorAction Stop")
    return r.returncode == 0, (r.stderr or "").strip()


def run(app: WinApp) -> None:
    if app.app_ids:
        os.startfile(f"shell:AppsFolder\\{app.family_name}!{app.app_ids[0]}")


def terminate(app: WinApp) -> int:
    import psutil
    n = 0
    loc = wu.norm_path(app.install_location)
    for pr in psutil.process_iter(["exe"]):
        if pr.info["exe"] and loc and wu.is_under(pr.info["exe"], loc):
            try:
                pr.kill()
                n += 1
            except psutil.Error:
                pass
    return n


def reset_store() -> None:
    wu.run_hidden(["wsreset.exe"], timeout=300)


def leftovers(app: WinApp):
    """Per-user data and registry left after removal."""
    from .leftovers import Leftover
    import winreg
    out = []
    if os.path.isdir(app.data_folder):
        out.append(Leftover("folder", app.data_folder, "App data folder", True, size=wu.dir_size(app.data_folder)))
    for sub in (r"Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\Repository"
                r"\Packages\\" + app.full_name,
                r"Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppContainer"
                r"\Storage\\" + app.family_name.lower()):
        sub = sub.replace("\\\\", "\\")
        if wu.key_exists(winreg.HKEY_CURRENT_USER, sub):
            out.append(Leftover("regkey", wu.join_reg_path(winreg.HKEY_CURRENT_USER, sub), "App registration", True,
                                hive=winreg.HKEY_CURRENT_USER, sub=sub))
    return out
