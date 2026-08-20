"""Start the ChronoDesk API and frontend development servers together."""

from __future__ import annotations

import importlib.util
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent


def check_prerequisites(project_root: Path = PROJECT_ROOT) -> list[str]:
    """Return actionable setup errors without starting either server."""
    errors: list[str] = []
    frontend_dir = project_root / "frontend"

    if importlib.util.find_spec("uvicorn") is None:
        errors.append(
            "Python dependencies are missing. Run: pip install -r requirements.txt"
        )
    if shutil.which("npm") is None:
        errors.append("npm was not found. Install Node.js 20 or newer, then try again.")
    elif not (frontend_dir / "node_modules" / ".bin" / "vite").exists():
        errors.append(
            "Frontend dependencies are missing. Run: npm --prefix frontend install"
        )
    if not (project_root / ".env").exists():
        errors.append(
            "The .env file is missing. Run: cp .env.example .env, then add GEMINI_API_KEY."
        )

    return errors


def server_commands(project_root: Path = PROJECT_ROOT) -> tuple[list[str], list[str]]:
    backend = [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.main:app",
        "--reload",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
    ]
    frontend = [
        "npm",
        "--prefix",
        str(project_root / "frontend"),
        "run",
        "dev",
    ]
    return backend, frontend


def _start_process(command: list[str]) -> subprocess.Popen[bytes]:
    options: dict[str, object] = {"cwd": PROJECT_ROOT}
    if os.name == "posix":
        options["start_new_session"] = True
    elif os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen(command, **options)


def _stop_process(process: subprocess.Popen[bytes], timeout: float = 5.0) -> None:
    if process.poll() is not None:
        return

    if os.name == "posix":
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    else:
        process.terminate()

    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        else:
            process.kill()
        process.wait()


def run() -> int:
    problems = check_prerequisites()
    if problems:
        print("Cannot start Watch Finder:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    backend_command, frontend_command = server_commands()
    processes: list[tuple[str, subprocess.Popen[bytes]]] = []

    try:
        processes.append(("backend", _start_process(backend_command)))
        processes.append(("frontend", _start_process(frontend_command)))
        print("\nWatch Finder is starting:")
        print("  App: http://localhost:5173")
        print("  API: http://127.0.0.1:8000")
        print("Press Ctrl-C to stop both servers.\n")

        while True:
            for name, process in processes:
                exit_code = process.poll()
                if exit_code is not None:
                    print(f"{name.capitalize()} stopped with exit code {exit_code}.")
                    return exit_code or 1
            time.sleep(0.25)
    except KeyboardInterrupt:
        print("\nStopping Watch Finder...")
        return 0
    except OSError as exc:
        print(f"Could not start Watch Finder: {exc}", file=sys.stderr)
        return 1
    finally:
        for _name, process in reversed(processes):
            _stop_process(process)


if __name__ == "__main__":
    raise SystemExit(run())
