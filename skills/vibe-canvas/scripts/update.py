#!/usr/bin/env python3
"""Replace this skill folder with the latest version from vibeus/canvas-skill when VERSION differs.

Checks at most once a day unless --force is given. Always exits 0 and prints one line,
so a failed check never blocks the skill.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.dont_write_bytecode = True

REPO = "vibeus/canvas-skill"
SUBDIR = "skills/vibe-canvas"
CLONE_URLS = [f"https://github.com/{REPO}.git", f"git@github.com:{REPO}.git"]
CHECK_INTERVAL = 24 * 60 * 60
TIMEOUT = 60

SKILL_DIR = Path(__file__).resolve().parent.parent
VERSION_FILE = SKILL_DIR / "VERSION"
STAMP_FILE = SKILL_DIR / ".last-update-check"
GIT_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}


def run(args, cwd=None):
    return subprocess.run(
        args, cwd=cwd, env=GIT_ENV, capture_output=True, text=True, timeout=TIMEOUT, check=True
    ).stdout


def is_git_checkout(path):
    try:
        run(["git", "ls-files", "--error-unmatch", "SKILL.md"], cwd=path)
        return True
    except (subprocess.SubprocessError, OSError):
        return False


def read_version(path):
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def checked_recently():
    try:
        return time.time() - float(STAMP_FILE.read_text()) < CHECK_INTERVAL
    except (OSError, ValueError):
        return False


def write_stamp():
    try:
        STAMP_FILE.write_text(str(time.time()))
    except OSError:
        pass


def remote_version_via_gh():
    if not shutil.which("gh"):
        return None
    try:
        out = run(["gh", "api", "-H", "Accept: application/vnd.github.raw",
                   f"repos/{REPO}/contents/{SUBDIR}/VERSION"])
    except (subprocess.SubprocessError, OSError):
        return None
    return out.strip() or None


def sparse_clone(dest):
    errors = []
    for url in CLONE_URLS:
        try:
            run(["git", "clone", "--depth", "1", "--filter=blob:none", "--sparse", url, str(dest)])
            run(["git", "sparse-checkout", "set", SUBDIR], cwd=dest)
            return dest / SUBDIR
        except (subprocess.SubprocessError, OSError) as e:
            errors.append(getattr(e, "stderr", "") or str(e))
            shutil.rmtree(dest, ignore_errors=True)
    lines = errors[-1].strip().splitlines() if errors else []
    fatal = [l for l in lines if l.startswith("fatal:")]
    raise RuntimeError((fatal or lines or ["git clone failed"])[0])


def install(source):
    parent = SKILL_DIR.parent
    staged = parent / f".{SKILL_DIR.name}.new"
    old = parent / f".{SKILL_DIR.name}.old"
    for p in (staged, old):
        shutil.rmtree(p, ignore_errors=True)
    shutil.copytree(source, staged, ignore=shutil.ignore_patterns(".git"))
    SKILL_DIR.rename(old)
    staged.rename(SKILL_DIR)
    shutil.rmtree(old, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="check even if checked within the last day")
    args = parser.parse_args()

    if is_git_checkout(SKILL_DIR):
        print("vibe-canvas: development checkout, update check skipped.")
        return
    if not args.force and checked_recently():
        print("vibe-canvas: checked for updates within the last day.")
        return

    local = read_version(VERSION_FILE)
    remote = remote_version_via_gh()
    if remote and remote == local:
        write_stamp()
        print(f"vibe-canvas: up to date ({local}).")
        return

    with tempfile.TemporaryDirectory() as tmp:
        try:
            source = sparse_clone(Path(tmp) / "canvas-skill")
        except (RuntimeError, OSError) as e:
            print(f"vibe-canvas: update check failed ({e}); continuing with {local or 'current version'}.")
            return
        remote = read_version(source / "VERSION")
        if not remote or remote == local:
            write_stamp()
            print(f"vibe-canvas: up to date ({local}).")
            return
        try:
            install(source)
        except OSError as e:
            print(f"vibe-canvas: update to {remote} failed ({e}); continuing with {local or 'current version'}.")
            return
    write_stamp()
    print(f"vibe-canvas: updated {local or 'unversioned'} -> {remote}. Start a new conversation to use it.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # never block the skill on an update problem
        print(f"vibe-canvas: update check failed ({e}).")
