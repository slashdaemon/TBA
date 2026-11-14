#!/usr/bin/env python3
"""Check the pack's options.txt keybinds against a client that has actually run the pack.

The build gate (audit-artifacts.py) can only see options.txt. A mod whose bindings are NOT in
options.txt uses its own defaults, which can silently take a key the pack already assigned (how
StreamCraft's mic toggle lost M to JourneyMap in 2.0.0). Minecraft writes every registered
binding to an instance's options.txt, so after launching the pack once:

    py -3 scripts/check-keybinds.py "%APPDATA%/PrismLauncher/instances/<instance>/minecraft/options.txt"

Reports, and exits 1 on any of:
  - bindings the instance registers that the pack's options.txt doesn't set (add them, usually
    with the mod's default, after checking the key is free)
  - conflicts in the effective map (the pack's values over the instance's registered defaults)
Also lists pack bindings no mod registers any more (stale; delete them).
"""
from __future__ import annotations

import importlib.util, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("audit", ROOT / "scripts" / "audit-artifacts.py")
audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(audit)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    inst = audit.keybinds(Path(sys.argv[1]).read_text(encoding="utf-8"))
    pack = audit.keybinds((ROOT / "options.txt").read_text(encoding="utf-8"))
    missing = sorted(set(inst) - set(pack))
    stale = sorted(set(pack) - set(inst))
    conflicts = audit.keybind_conflicts({**inst, **pack})
    for k in missing:
        print(f"MISSING from pack options.txt: {k}:{inst[k]}")
    for c in conflicts:
        print(f"CONFLICT: {c}")
    for k in stale:
        print(f"stale (no mod registers it): {k}")
    print(f"{len(inst)} registered, {len(pack)} in pack: {len(missing)} missing, "
          f"{len(conflicts)} conflicts, {len(stale)} stale")
    return 1 if missing or conflicts else 0


if __name__ == "__main__":
    sys.exit(main())
