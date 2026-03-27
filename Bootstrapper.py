"""
kZam Tracer — Auto-Updater / Bootstrapper
==========================================
Bundled as its own tiny .exe (kZam_Updater.exe).

Flow
----
1.  Read the local version from version.json (next to the exe).
2.  Hit the GitHub Releases API for the latest release tag.
3.  If a newer version exists:
        a. Show a small Tkinter dialog asking the user if they want to update.
        b. Download the new kZam_Tracer.exe into a temp file.
        c. Use a .bat trampoline to swap the old exe → new exe after this
           process exits (Windows won't let you overwrite a running exe).
        d. Launch the trampoline and exit.
4.  If already up-to-date (or user says "Not now"), launch kZam_Tracer.exe.
"""

import json
import os
import sys
import subprocess
import tempfile
import threading
import tkinter as tk
from tkinter import ttk
import urllib.request
import urllib.error

# ── Config ────────────────────────────────────────────────────────────────────
GITHUB_USER   = "YOUR_GITHUB_USERNAME"   # ← change this
GITHUB_REPO   = "kzam-tracer"
API_URL       = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/releases/latest"
MAIN_EXE_NAME = "kZam_Tracer.exe"

# ── Helpers ───────────────────────────────────────────────────────────────────

def _exe_dir() -> str:
    """Directory where both exes live (works for both frozen and script mode)."""
    return os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))


def _local_version() -> str:
    """Read version from version.json sitting next to the exe."""
    vfile = os.path.join(_exe_dir(), "version.json")
    try:
        with open(vfile, encoding="utf-8") as f:
            return json.load(f)["version"]
    except Exception:
        return "0.0.0"


def _parse_version(v: str) -> tuple:
    """'1.2.3' → (1, 2, 3)  for numeric comparison."""
    try:
        return tuple(int(x) for x in v.lstrip("v").split("."))
    except ValueError:
        return (0, 0, 0)


def _fetch_latest_release() -> dict | None:
    """
    Returns a dict with keys: tag_name, body, download_url
    or None on any network / parse error.
    """
    req = urllib.request.Request(
        API_URL,
        headers={"Accept": "application/vnd.github+json",
                 "User-Agent": "kZam-Tracer-Updater"}
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        return None

    tag = data.get("tag_name", "")
    notes = data.get("body", "")

    # Find the asset that matches MAIN_EXE_NAME
    for asset in data.get("assets", []):
        if asset["name"] == MAIN_EXE_NAME:
            return {"tag": tag, "notes": notes, "url": asset["browser_download_url"]}
    return None


# ── Update dialog ─────────────────────────────────────────────────────────────

class UpdateDialog(tk.Tk):
    """
    Small dialog shown when an update is available.
    Result stored in self.choice: 'update' | 'skip'
    """

    DARK   = "#1a1a1a"
    ACCENT = "#00ff88"

    def __init__(self, current: str, latest: str, notes: str):
        super().__init__()
        self.choice = "skip"
        self.title("kZam Tracer — Update Available")
        self.geometry("400x260")
        self.resizable(False, False)
        self.configure(bg=self.DARK)
        self.attributes("-topmost", True)

        # Header
        tk.Label(self, text="✨  Update Available",
                 fg=self.ACCENT, bg=self.DARK,
                 font=("Courier", 13, "bold")).pack(pady=(20, 4))

        tk.Label(self, text=f"v{current}  →  {latest}",
                 fg="#888", bg=self.DARK,
                 font=("Courier", 10)).pack()

        # Release notes (scrollable)
        frame = tk.Frame(self, bg="#252525", padx=10, pady=8)
        frame.pack(fill="both", expand=True, padx=20, pady=10)
        txt = tk.Text(frame, bg="#252525", fg="#ccc",
                      font=("Courier", 8), relief="flat",
                      wrap="word", height=5)
        txt.insert("1.0", notes or "No release notes.")
        txt.config(state="disabled")
        txt.pack(fill="both", expand=True)

        # Buttons
        btn_row = tk.Frame(self, bg=self.DARK)
        btn_row.pack(pady=(0, 16))
        tk.Button(btn_row, text="Update Now",
                  bg=self.ACCENT, fg="black",
                  font=("Courier", 9, "bold"), relief="flat",
                  padx=14, pady=6, cursor="hand2",
                  command=self._do_update).pack(side="left", padx=8)
        tk.Button(btn_row, text="Not Now",
                  bg="#333", fg="white",
                  font=("Courier", 9), relief="flat",
                  padx=14, pady=6, cursor="hand2",
                  command=self._do_skip).pack(side="left", padx=8)

    def _do_update(self):
        self.choice = "update"
        self.destroy()

    def _do_skip(self):
        self.choice = "skip"
        self.destroy()


class DownloadDialog(tk.Tk):
    """
    Progress bar shown while the new exe is downloading.
    """

    DARK   = "#1a1a1a"
    ACCENT = "#00ff88"

    def __init__(self, url: str, dest: str):
        super().__init__()
        self.url  = url
        self.dest = dest
        self.success = False

        self.title("kZam Tracer — Downloading Update")
        self.geometry("380x130")
        self.resizable(False, False)
        self.configure(bg=self.DARK)
        self.attributes("-topmost", True)

        tk.Label(self, text="Downloading update…",
                 fg="#ccc", bg=self.DARK,
                 font=("Courier", 10)).pack(pady=(24, 8))

        self.progress = ttk.Progressbar(self, length=320, mode="determinate")
        self.progress.pack(padx=30)

        self.status_var = tk.StringVar(value="Connecting…")
        tk.Label(self, textvariable=self.status_var,
                 fg="#555", bg=self.DARK,
                 font=("Courier", 8)).pack(pady=6)

        # Start download in background thread
        threading.Thread(target=self._download, daemon=True).start()

    def _download(self):
        try:
            with urllib.request.urlopen(self.url, timeout=60) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                chunk = 65536  # 64 KB chunks
                with open(self.dest, "wb") as f:
                    while True:
                        data = resp.read(chunk)
                        if not data:
                            break
                        f.write(data)
                        downloaded += len(data)
                        if total:
                            pct = downloaded / total * 100
                            mb  = downloaded / 1_048_576
                            self.after(0, lambda p=pct, m=mb: self._update_progress(p, m))
            self.success = True
        except Exception as exc:
            self.after(0, lambda: self.status_var.set(f"Error: {exc}"))
        finally:
            self.after(500, self.destroy)

    def _update_progress(self, pct: float, mb: float):
        self.progress["value"] = pct
        self.status_var.set(f"{mb:.1f} MB  ({pct:.0f}%)")


# ── Swap logic ────────────────────────────────────────────────────────────────

def _swap_and_relaunch(new_exe_path: str):
    """
    Creates a .bat file that:
      1. Waits for this updater process to exit  (ping loop).
      2. Replaces kZam_Tracer.exe with the downloaded file.
      3. Writes the new version.json.
      4. Launches the new kZam_Tracer.exe.
      5. Deletes itself.

    We use a .bat because Windows won't let a process overwrite its own
    running executable; the bat runs after we exit.
    """
    exe_dir    = _exe_dir()
    target_exe = os.path.join(exe_dir, MAIN_EXE_NAME)
    bat_path   = os.path.join(tempfile.gettempdir(), "kzam_update_swap.bat")
    pid        = os.getpid()

    bat = f"""@echo off
:wait
tasklist /fi "PID eq {pid}" 2>nul | find /i "{pid}" >nul
if not errorlevel 1 (
    ping -n 2 127.0.0.1 >nul
    goto wait
)
move /y "{new_exe_path}" "{target_exe}"
start "" "{target_exe}"
del "%~f0"
"""
    with open(bat_path, "w") as f:
        f.write(bat)

    subprocess.Popen(
        ["cmd.exe", "/c", bat_path],
        creationflags=subprocess.CREATE_NO_WINDOW
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    local_ver = _local_version()
    release   = _fetch_latest_release()

    should_update = False

    if release and _parse_version(release["tag"]) > _parse_version(local_ver):
        dlg = UpdateDialog(local_ver, release["tag"], release["notes"])
        dlg.mainloop()
        should_update = (dlg.choice == "update")

    if should_update and release:
        tmp_path = os.path.join(tempfile.gettempdir(), f"kZam_Tracer_new.exe")
        dl = DownloadDialog(release["url"], tmp_path)
        dl.mainloop()

        if dl.success:
            _swap_and_relaunch(tmp_path)
            sys.exit(0)   # bat takes over from here

    # No update or user skipped — just launch the main app
    main_exe = os.path.join(_exe_dir(), MAIN_EXE_NAME)
    if os.path.exists(main_exe):
        subprocess.Popen([main_exe])
    else:
        # Dev mode fallback: run the Python source directly
        src = os.path.join(os.path.dirname(__file__), "..", "src", "ghost_tracer.py")
        subprocess.Popen([sys.executable, os.path.abspath(src)])


if __name__ == "__main__":
    main()