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

Usage: py -3 scripts/audit-artifacts.py dist/TBA-2.0.1.mrpack dist/TBA-2.0.1.zip ...
"""
from __future__ import annotations

import fnmatch, json, sys, zipfile
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
MODRINTH_HOSTS = {"cdn.modrinth.com", "github.com", "raw.githubusercontent.com", "gitlab.com"}
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
