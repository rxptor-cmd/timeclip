import os
import subprocess
from pathlib import Path
from typing import Optional


def get_git_branch(cwd: Optional[str] = None) -> str:
    target = cwd or os.getcwd()
    try:
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        res = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=target,
            capture_output=True,
            text=True,
            timeout=1.5,
            startupinfo=startupinfo,
        )
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception:
        pass
    return ""


def capture_context(
    cwd: Optional[str] = None,
    git_branch: Optional[str] = None,
    exit_code: Optional[int] = None,
) -> dict:
    resolved_cwd = str(Path(cwd or os.getcwd()).resolve())
    resolved_branch = git_branch if git_branch is not None else get_git_branch(resolved_cwd)
    return {
        "cwd": resolved_cwd,
        "git_branch": resolved_branch,
        "exit_code": exit_code,
    }
