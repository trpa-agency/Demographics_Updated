"""Helpers for the double-click scripts in the tools folder.

The scripts in tools/ are for people who do not use a command line. Each one
asks a few questions, runs one toolkit command, and waits for Enter before its
window closes.

This module does four jobs for those scripts:

1. Finds a Python that has pandas, numpy, requests, and openpyxl. Windows may
   open a double-clicked .py file with a Python that lacks them. When that
   happens the script restarts itself in the ArcGIS Pro Python environment.
2. Asks questions and checks the answers, such as a four-digit year.
3. Runs a toolkit command, the same as typing
   python -m trpa_demographics <command> in a terminal.
4. Keeps the window open at the end, including after an error.

How the Python is chosen, in order:

* The Python already running, when it has the four packages.
* The python.exe named in the TRPA_PYTHON environment variable.
* ArcGIS Pro's propy.bat, which runs ArcGIS Pro's active environment.

This module imports only the Python standard library. It must stay that way,
because it runs before anyone knows whether pandas is available.
"""
from __future__ import annotations

import os
import subprocess
import sys
import traceback
from pathlib import Path
from typing import List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
REQUIRED_PACKAGES = ("pandas", "numpy", "requests", "openpyxl")
PYTHON_VARIABLE = "TRPA_PYTHON"
RESTART_MARKER = "TRPA_TOOLS_RESTARTED"


def _missing_packages() -> List[str]:
    missing = []
    for name in REQUIRED_PACKAGES:
        try:
            __import__(name)
        except ImportError:
            missing.append(name)
    return missing


def _other_python() -> Optional[List[str]]:
    """Return the command that starts a better Python, or None when none is found."""
    chosen = os.environ.get(PYTHON_VARIABLE)
    if chosen:
        return [chosen] if Path(chosen).is_file() else None
    program_files = os.environ.get("PROGRAMFILES", r"C:\Program Files")
    propy = Path(program_files) / "ArcGIS" / "Pro" / "bin" / "Python" / "Scripts" / "propy.bat"
    return [str(propy)] if propy.is_file() else None


def ensure_environment(script: str) -> None:
    """Restart the calling script in a Python that has the toolkit's packages.

    Returns when the running Python is ready. Otherwise starts the script again
    in the other Python, waits for it, and exits with its exit code.
    """
    missing = _missing_packages()
    if not missing:
        return
    command = _other_python()
    if command is None or os.environ.get(RESTART_MARKER):
        print(f"This Python ({sys.executable}) is missing: {', '.join(missing)}.")
        if os.environ.get(PYTHON_VARIABLE):
            print(f"{PYTHON_VARIABLE} is set to {os.environ[PYTHON_VARIABLE]}. Check that the file exists and has these packages.")
        else:
            print("ArcGIS Pro was not found in the usual place.")
            print(f"Set {PYTHON_VARIABLE} to the full path of a python.exe that has pandas. See docs/setup.md.")
        pause_before_close()
        sys.exit(1)
    print(f"Restarting in {command[0]} ...", flush=True)
    env = dict(os.environ, **{RESTART_MARKER: "1"})
    result = subprocess.call(command + [str(Path(script).resolve())] + sys.argv[1:], env=env)
    sys.exit(result)


def ask(prompt: str, default: Optional[str] = None, required: bool = True) -> str:
    """Ask a question. Pressing Enter returns the default, or asks again when an answer is required."""
    suffix = f" [{default}]" if default else ""
    while True:
        answer = input(f"{prompt}{suffix}: ").strip()
        if answer:
            return answer
        if default is not None:
            return default
        if not required:
            return ""
        print("  Please type an answer.")


def ask_year(prompt: str, default: Optional[int] = None) -> int:
    """Ask for a four-digit year and ask again until one is typed."""
    while True:
        answer = ask(prompt, str(default) if default else None)
        if answer.isdigit() and len(answer) == 4:
            return int(answer)
        print("  Please type a four-digit year, for example 2024.")


def ask_yes_no(prompt: str) -> bool:
    """Ask a Y or N question and ask again until Y or N is typed."""
    while True:
        answer = ask(f"{prompt} (Y/N)").upper()
        if answer in ("Y", "YES"):
            return True
        if answer in ("N", "NO"):
            return False
        print("  Please type Y or N.")


def run_command(arguments: List[str]) -> bool:
    """Run one toolkit command. Returns True when it finished without an error.

    Same as typing: python -m trpa_demographics <arguments>
    Errors are printed, not raised, so the window stays open to read them.
    """
    from trpa_demographics.__main__ import main  # needs pandas, so imported here

    print("\nRunning: python -m trpa_demographics " + " ".join(f'"{a}"' if " " in a else a for a in arguments))
    print()
    os.chdir(REPO_ROOT)
    try:
        main(arguments)
        return True
    except SystemExit as exc:  # argparse and some commands stop this way
        return exc.code in (0, None)
    except KeyboardInterrupt:
        print("\nStopped.")
        return False
    except Exception:
        print("\nThe command stopped with an error:\n")
        traceback.print_exc()
        return False


def pause_before_close() -> None:
    """Wait for Enter so a double-clicked window stays open."""
    try:
        input("\nPress Enter to close this window.")
    except EOFError:  # no keyboard attached, such as a scheduled run
        pass
