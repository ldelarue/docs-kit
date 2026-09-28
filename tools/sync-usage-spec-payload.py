#!/usr/bin/env python3
"""Regenerate shared/mise/usage-spec.py from src/docs_kit/usage_spec.py.

The .docs-kit sparse payload ships only /shared/mise/, so the shipped task
script must run stand-alone: it stays a BYTE COPY of the module below the
payload sentinel. Edit the module, run this, commit both files
(tests/test_usage_spec.py fails if they ever diverge).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from docs_kit.usage_spec import PAYLOAD_SENTINEL

HEADER = (
    "#!/usr/bin/env python3\n"
    "# GENERATED COPY (payload) of src/docs_kit/usage_spec.py - do not edit here.\n"
    "# The pulled .docs-kit layer ships only /shared/mise/, so this byte copy\n"
    "# is what makes the old `python $DOCS_KIT/shared/mise/usage-spec.py --...\n"
    "# task shape keep working for shim (no-venv-package) consumers. Edit the\n"
    "# module, then run: python tools/sync-usage-spec-payload.py\n"
)


def main() -> int:
    kit = Path(__file__).resolve().parents[1]
    module = kit / "src/docs_kit/usage_spec.py"
    payload = kit / "shared/mise/usage-spec.py"
    payload.write_text(
        HEADER + PAYLOAD_SENTINEL + "\n" + module.read_text(encoding="utf-8"),
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {payload.relative_to(kit)} from {module.relative_to(kit)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
