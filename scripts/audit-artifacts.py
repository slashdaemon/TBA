#!/usr/bin/env python3
"""Store-compliance gate for built modpack files (run by build-variants.py; also usable alone).

Fails when an artifact would be rejected or is wrong to ship:
  - a bundled jar/zip under mods/, resourcepacks/ or shaderpacks/ (any overrides folder) that is
    not in ALLOWED_OVERRIDES. Every store-hosted project must be a store reference instead:
    CurseForge rejects bundled jars of CurseForge projects; Modrinth rejects bundled files that
    are on Modrinth or that we have no right to redistribute.
  - .mrpack download URLs outside Modrinth's allowed hosts.
  - root-level override files or top-level folders outside the allowlists (stray junk).
  - anything that looks like a secret (.ssh, ed25519 keys, .env, .pem).
  - a key bound to two actions in the shipped options.txt (outside ALLOWED_SHARED_KEYS).
    scripts/check-keybinds.py covers what this can't see: mod defaults missing from options.txt.

Usage: py -3 scripts/audit-artifacts.py dist/TBA-2.0.1.mrpack dist/TBA-2.0.1.zip ...
"""
from __future__ import annotations

import fnmatch, json, re, sys, zipfile
from collections import Counter
from urllib.parse import urlparse

# Bundled files allowed per store: filename glob -> reason (licence permits redistribution and
# the project is not hosted on that store). Keep this list short and justified.
ALLOWED_OVERRIDES = {
    "curseforge": {
        "better-sleep-*.jar": "Better Sleep, Modrinth-only, MIT",
        "matthiesen-core-*.jar": "Matthiesen Core (Better Sleep library), Modrinth-only, MIT",
        "SPBR_*.zip": "SPBR resource pack, Modrinth-only, GPL-3.0-or-later",
        "ModernPSX-*.zip": "Modern PSX shaders, Modrinth-only, MIT",
    },
    "modrinth": {
        "framework-neoforge-*.jar": "Framework (MrCrayfish), CurseForge-only, LGPL-2.1",
        "mighty_mail-neoforge-*.jar": "Mighty Mail (MrCrayfish), CurseForge-only, MIT",
    },
}
# Keys deliberately shared by several bindings: each works in a different context (a modifier
# key, a specific screen, or only while piloting). Any other key bound twice in the shipped
# options.txt fails the gate: on NeoForge only one binding receives the press.
ALLOWED_SHARED_KEYS = {
    "key.keyboard.left.alt": {"key_create.keyinfo.alt_modifier", "key_create.keyinfo.toolmenu",
                              "key_create.keyinfo.toolbelt", "key_key.effortlessbuilding.open_radial_menu",
                              "key_key.immersive_aircraft.free_look", "key_keyinfo.copycats.fill_copycat"},
    "key.keyboard.left.control": {"key_create.keyinfo.ctrl_modifier", "key_key.sprint"},
    "key.keyboard.left.shift": {"key_create.keyinfo.shift_modifier", "key_key.sneak"},
    "key.keyboard.w": {"key_key.ponder.ponder", "key_key.forward"},           # Ponder: tooltip hover
    "key.mouse.middle": {"key_key.clientsort.op.sort", "key_key.pickItem"},     # sort: inventory screen
    "key.keyboard.k": {"key_key.journeymap.create_waypoint", "key_key.journeymap.fullscreen_create_waypoint"},
    "key.keyboard.left.bracket": {"key_genshinstrument.keymaps.transpose_down_modifier",
                                  "key_key.journeymap.minimap_type"},       # transpose: instrument screen
    "key.keyboard.right.bracket": {"key_genshinstrument.keymaps.transpose_up_modifier",
                                   "key_evenmoreinstruments.keymaps.instrument_type_modifier"},
    "key.keyboard.grave.accent": {"key_evenmoreinstruments.keymaps.record",
                                  "key_key.immersive_aircraft.mouse_control"},  # piloting only
}


def keybinds(options_text: str) -> dict[str, str]:
    return {m.group(1): m.group(2) for m in re.finditer(r"^(key_[^:\s]+):(\S+)\s*$", options_text, re.M)}


def keybind_conflicts(binds: dict[str, str]) -> list[str]:
    by_key: dict[str, set[str]] = {}
    for name, key in binds.items():
        if key != "key.keyboard.unknown":
            by_key.setdefault(key, set()).add(name)
    out = []
    for key, names in sorted(by_key.items()):
        if len(names) > 1 and not names <= ALLOWED_SHARED_KEYS.get(key, set()):
            out.append(f"{key} bound to {', '.join(sorted(names))}")
    return out


MODRINTH_HOSTS ={"cdn.modrinth.com", "github.com", "raw.githubusercontent.com", "gitlab.com"}
ROOT_FILES = {"options.txt", "servers.dat"}
TOP_DIRS = {"mods", "resourcepacks", "shaderpacks", "config", "defaultconfigs", "journeymap", "minescript"}
CONTENT_DIRS = {"mods", "resourcepacks", "shaderpacks"}
SECRET_MARKERS = (".ssh/", "ed25519", "/.env", ".pem")
OVERRIDE_ROOTS = ("overrides/", "client-overrides/", "server-overrides/")


def audit(path: str) -> list[str]:
    store = "modrinth" if path.endswith(".mrpack") else "curseforge"
    allowed = ALLOWED_OVERRIDES[store]
    z = zipfile.ZipFile(path)
    problems, bundled, links = [], [], 0

    if store == "modrinth":
        idx = json.loads(z.read("modrinth.index.json"))
        links = len(idx["files"])
        for f in idx["files"]:
            for u in f["downloads"]:
                if urlparse(u).netloc not in MODRINTH_HOSTS:
                    problems.append(f"download host not allowed on Modrinth: {f['path']} <- {u}")
    else:
        links = len(json.loads(z.read("manifest.json"))["files"])

    for opts in [n for n in z.namelist() if n.endswith("overrides/options.txt")]:
        for c in keybind_conflicts(keybinds(z.read(opts).decode("utf-8", "replace"))):
            problems.append(f"keybind conflict in {opts}: {c}")

    for n in z.namelist():
        low = "/" + n.lower()
        if any(m in low for m in SECRET_MARKERS):
            problems.append(f"possible secret: {n}")
        root = next((r for r in OVERRIDE_ROOTS if n.startswith(r)), None)
        if root is None or n.endswith("/"):
            continue
        rel = n[len(root):]
        parts = rel.split("/")
        if len(parts) == 1:
            if rel not in ROOT_FILES:
                problems.append(f"unexpected root override file: {n}")
            continue
        if parts[0] not in TOP_DIRS:
            problems.append(f"unexpected override folder: {n}")
        if parts[0] in CONTENT_DIRS and rel.lower().endswith((".jar", ".zip")):
            name = parts[-1]
            reason = next((r for g, r in allowed.items() if fnmatch.fnmatch(name, g)), None)
            if reason:
                bundled.append(f"{name} ({reason})")
            else:
                problems.append(f"bundled {parts[0][:-1] if parts[0] != 'mods' else 'mod'} not allowed on "
                                f"{store}: {n} -> use a {store} reference or add a justified exception")

    print(f"{path}: {links} {store} references, {len(bundled)} allowed bundled files, "
          f"{len(problems)} problem(s)")
    for b in bundled:
        print(f"    allowed: {b}")
    for p in problems:
        print(f"    FAIL: {p}")
    return problems


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    failed = sum(bool(audit(p)) for p in sys.argv[1:])
    print("GATE:", "PASS" if not failed else f"FAIL ({failed} artifact(s))")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
