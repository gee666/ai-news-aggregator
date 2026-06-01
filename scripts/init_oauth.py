"""Initialize credentials/sessions for collectors and the pi agent.

The LLM is served by the local pi agent, which keeps its own OAuth credentials
in ``$PI_CODING_AGENT_DIR/auth.json`` (default ``~/.pi/agent/auth.json``).

For the ``pi`` provider this helper either:
  * launches an interactive ``pi`` login (so you can authenticate inside the
    container), or
  * copies an existing host ``auth.json`` (``--import-auth``) into the pi
    config directory so OAuth works without an interactive login.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings


def _pi_config_dir() -> Path:
    return Path(os.getenv("PI_CODING_AGENT_DIR", str(Path.home() / ".pi/agent")))


def init_pi(args: argparse.Namespace) -> None:
    settings = get_settings()
    config_dir = _pi_config_dir()
    auth_target = config_dir / "auth.json"

    if args.import_auth:
        source = Path(args.import_auth) if isinstance(args.import_auth, str) else (
            settings.pi_auth_json_path or Path("/host_pi_auth/auth.json")
        )
        if not source.exists():
            raise SystemExit(f"No pi auth.json found at {source}")
        auth_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, auth_target)
        os.chmod(auth_target, 0o600)
        print(f"Copied pi auth credentials from {source} to {auth_target}")
        return

    # Interactive login inside the container/host.
    print(f"Launching interactive pi login (config dir: {config_dir}).")
    print("Authenticate your provider, then exit pi to continue.")
    subprocess.run([settings.pi_bin], check=False)
    if auth_target.exists():
        print(f"pi credentials present at {auth_target}")
    else:
        print(f"WARNING: no auth.json found at {auth_target} after login")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("provider", choices=["gmail", "telegram", "pi"])
    parser.add_argument(
        "--import-auth",
        nargs="?",
        const=True,
        default=False,
        help="copy an existing pi auth.json into the pi config dir "
        "(optionally pass a path; defaults to PI_AUTH_JSON_PATH)",
    )
    args = parser.parse_args()

    if args.provider == "pi":
        init_pi(args)
        return
    raise SystemExit(f"OAuth initialization for {args.provider} is not implemented in this phase")


if __name__ == "__main__":
    main()
