"""Start Nexus for development with one command: ``python start.py``

First run: creates the backend virtual environment and installs dependencies (needs Python 3.10+
and Node.js). Then starts the backend (http://localhost:8000) and the frontend
(http://localhost:5173). Ctrl+C stops both.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
WINDOWS = sys.platform == "win32"


def venv_python() -> Path:
    for name in (".venv311", ".venv"):
        python = BACKEND / name / ("Scripts/python.exe" if WINDOWS else "bin/python")
        if python.exists():
            return python
    return BACKEND / ".venv" / ("Scripts/python.exe" if WINDOWS else "bin/python")


def run(command: list[str], cwd: Path) -> None:
    print(f"> {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def setup() -> Path:
    if sys.version_info < (3, 10):
        sys.exit(f"Nexus needs Python 3.10 or newer; this is {sys.version.split()[0]}.")
    npm = shutil.which("npm")
    if npm is None:
        sys.exit("Node.js (npm) is required for the frontend: https://nodejs.org")
    python = venv_python()
    if not python.exists():
        run([sys.executable, "-m", "venv", str(python.parent.parent)], BACKEND)
        run([str(python), "-m", "pip", "install", "-r", "requirements.txt"], BACKEND)
    if not (FRONTEND / "node_modules").exists():
        run([npm, "install"], FRONTEND)
    return python


def main() -> None:
    python = setup()
    npm = shutil.which("npm")
    processes = [
        subprocess.Popen([str(python), "-m", "uvicorn", "app.main:app", "--reload", "--port", "8000"], cwd=BACKEND),
        subprocess.Popen([npm, "run", "dev", "--", "--port", "5173"], cwd=FRONTEND),
    ]
    print("\nNexus is starting: open http://localhost:5173 (Ctrl+C to stop)\n", flush=True)
    try:
        while all(p.poll() is None for p in processes):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    main()
