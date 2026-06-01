#!/usr/bin/env python3
"""One-shot launcher for News Bot AI.

This script brings the whole stack up:

  * verifies Docker + Docker Compose are available
  * makes sure a .env exists (seeded from .env.example)
  * builds the images
  * ensures the pi agent is authenticated (OAuth) by either
      - copying an existing auth.json (standard ~/.pi/agent/auth.json or a
        custom path), or
      - logging in interactively (browser) inside the container
  * starts everything with `docker compose up`

If Docker is already running and pi is already logged in, it simply (re)starts
the stack without asking anything.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
COMPOSE_FILE = ROOT / "compose.yaml"
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
STANDARD_AUTH = Path.home() / ".pi/agent/auth.json"
AUTH_IN_CONTAINER = "/root/.pi/agent/auth.json"


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def info(msg: str) -> None:
    print(f"\033[36m==>\033[0m {msg}")


def warn(msg: str) -> None:
    print(f"\033[33m!!\033[0m {msg}")


def die(msg: str) -> None:
    print(f"\033[31mERROR:\033[0m {msg}", file=sys.stderr)
    sys.exit(1)


def run(cmd: list[str], *, env: dict | None = None, capture: bool = False, check: bool = True) -> subprocess.CompletedProcess:
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(
        cmd,
        cwd=str(ROOT),
        env=full_env,
        text=True,
        check=check,
        capture_output=capture,
    )


def ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        answer = ""
    return answer or (default or "")


# --------------------------------------------------------------------------- #
# environment checks
# --------------------------------------------------------------------------- #
def detect_compose() -> list[str]:
    if shutil.which("docker") is None:
        die("docker is not installed or not on PATH.")
    # Prefer the `docker compose` plugin, fall back to legacy `docker-compose`.
    try:
        run(["docker", "compose", "version"], capture=True)
        return ["docker", "compose"]
    except subprocess.CalledProcessError:
        pass
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    die("Docker Compose is not available (need `docker compose` or `docker-compose`).")
    return []  # unreachable


def ensure_docker_daemon() -> None:
    try:
        run(["docker", "info"], capture=True)
    except subprocess.CalledProcessError:
        die("Docker daemon is not running. Start Docker and re-run this script.")


def ensure_env_file() -> None:
    if ENV_FILE.exists():
        return
    if not ENV_EXAMPLE.exists():
        die(".env is missing and .env.example was not found.")
    shutil.copyfile(ENV_EXAMPLE, ENV_FILE)
    info(f"Created {ENV_FILE.name} from .env.example (edit it to add credentials).")


# --------------------------------------------------------------------------- #
# build / auth / up
# --------------------------------------------------------------------------- #
def build_images(compose: list[str]) -> None:
    info("Building Docker images (this can take a while the first time)...")
    run(compose + ["build"])


def pi_is_authenticated(compose: list[str]) -> bool:
    """Return True if auth.json already exists in the persisted pi_config volume."""
    try:
        result = run(
            compose
            + [
                "run",
                "--rm",
                "--no-deps",
                "-T",
                "app",
                "sh",
                "-c",
                f"test -f {AUTH_IN_CONTAINER} && echo FOUND || echo MISSING",
            ],
            capture=True,
            check=False,
        )
    except Exception:
        return False
    return "FOUND" in (result.stdout or "")


def import_auth(compose: list[str], auth_path: Path) -> None:
    auth_path = auth_path.expanduser().resolve()
    if not auth_path.exists():
        die(f"auth.json not found at {auth_path}")
    auth_dir = str(auth_path.parent)
    info(f"Importing pi credentials from {auth_path} ...")
    # The compose file maps ${PI_HOST_AUTH_DIR} -> /host_pi_auth; the import
    # helper copies /host_pi_auth/auth.json into the persisted pi_config volume.
    run(
        compose + ["run", "--rm", "app", "python", "scripts/init_oauth.py", "pi", "--import-auth"],
        env={"PI_HOST_AUTH_DIR": auth_dir},
    )
    info("pi credentials imported.")


def interactive_login(compose: list[str]) -> None:
    info("Launching interactive pi login inside the container.")
    info("Use pi's /login command, authenticate in your browser, then exit pi.")
    # No -T: we want an interactive TTY for the login flow.
    run(compose + ["run", "--rm", "app", "python", "scripts/init_oauth.py", "pi"], check=False)


def ensure_pi_auth(compose: list[str]) -> None:
    if pi_is_authenticated(compose):
        info("pi is already authenticated. Skipping login.")
        return

    print()
    info("pi is not authenticated yet. Choose how to provide credentials:")
    print("  1) Copy an existing auth.json")
    print("  2) Log in via browser (interactive)")
    choice = ask("Select option", "1")

    if choice == "2":
        interactive_login(compose)
    else:
        print()
        print(f"  a) Use standard location ({STANDARD_AUTH})")
        print("  b) Specify a custom auth.json path")
        sub = ask("Select option", "a")
        if sub == "b":
            path = ask("Path to auth.json")
            if not path:
                die("No path provided.")
            import_auth(compose, Path(path))
        else:
            import_auth(compose, STANDARD_AUTH)

    if not pi_is_authenticated(compose):
        warn("auth.json still not detected. The stack will start, but LLM calls will fail until pi is authenticated.")


def stack_up(compose: list[str]) -> None:
    info("Starting the stack (docker compose up -d)...")
    run(compose + ["up", "-d"])
    print()
    info("Stack is up. Useful commands:")
    print(f"  {' '.join(compose)} ps")
    print(f"  {' '.join(compose)} logs -f app")
    print(f"  {' '.join(compose)} down")
    print()
    info("API available at http://127.0.0.1:8000  (GET /health)")


def main() -> None:
    if not COMPOSE_FILE.exists():
        die(f"compose file not found: {COMPOSE_FILE}")

    compose = detect_compose()
    ensure_docker_daemon()
    ensure_env_file()
    build_images(compose)
    ensure_pi_auth(compose)
    stack_up(compose)


if __name__ == "__main__":
    main()
