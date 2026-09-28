"""`docs-kit serve` / `docs-kit build`: Zensical, run from docs-kit's own environment.

Zensical is a runtime dependency, so its version is pinned by pyproject/uv.lock
and `python -m zensical` always resolves - no PATH lookup, no uvx fallback.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8010
FREE_PORTS = (8000, 8999)  # default lease range, overridable via FREE_PORT_MIN/MAX


def zensical(*args: str) -> list[str]:
    return [sys.executable, "-m", "zensical", *args]


def port_free(port: int, host: str) -> bool:
    """True when nothing currently binds host:port (mirrors the serve bind)."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def lease_port(preferred: int, host: str) -> int:
    """PREFERRED when free, else the first free port in FREE_PORT_MIN..FREE_PORT_MAX."""
    try:
        lo = int(os.environ.get("FREE_PORT_MIN", FREE_PORTS[0]))
        hi = int(os.environ.get("FREE_PORT_MAX", FREE_PORTS[1]))
    except ValueError:
        sys.exit("ERROR: FREE_PORT_MIN/FREE_PORT_MAX must be integers")
    if not 1 <= lo <= hi <= 65535:
        sys.exit(f"ERROR: bad port range {lo}-{hi}")
    if 1 <= preferred <= 65535 and port_free(preferred, host):
        return preferred
    for port in range(lo, hi + 1):
        if port_free(port, host):
            return port
    sys.exit(f"ERROR: no free TCP port in {lo}-{hi} (preferred {preferred} is in use)")


def cmd_serve(root: Path, port: int | None, host: str) -> int:
    """Live-reload serve: pinned port (--port/$DOCS_PORT), else leased."""
    pinned = port
    if pinned is None and (env := os.environ.get("DOCS_PORT")):
        if not env.isdigit():
            sys.exit(f"ERROR: DOCS_PORT must be an integer (got: {env})")
        pinned = int(env)
    chosen = pinned if pinned is not None else lease_port(DEFAULT_PORT, host)
    dev_addr = f"{host}:{chosen}"
    print(f"serving docs on http://{dev_addr} (Ctrl-C to stop)")
    return subprocess.run(
        zensical("serve", "--dev-addr", dev_addr), cwd=root, check=False
    ).returncode


def cmd_build(root: Path) -> int:
    """Build the static site into site/ (clean cache)."""
    return subprocess.run(
        zensical("build", "--clean"), cwd=root, check=False
    ).returncode
