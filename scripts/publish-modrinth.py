#!/usr/bin/env python3
"""
Publish TBA to Modrinth: the Windows .mrpack only.

Modrinth modpack versions carry ONE .mrpack. Attaching the macOS/Linux variants as extra
files to the same version is what got TheBlockSurvival rejected (Content Rule 5.7,
"Unsupported project"), so this script uploads only TBA-X.Y.Z.mrpack. The per-OS variants
ship on GitHub releases (CurseForge keeps them as additional files; publish-curseforge.py).

The file must pass scripts/audit-artifacts.py (no bundled store-hosted content) or the
script refuses to upload. The loader is read from pack.toml.

Usage:
    # Dry-run to inspect metadata before publishing
    python scripts/publish-modrinth.py --version 1.0.5 \\
        --changelog-file docs/release-notes-v1.0.5.md --dry-run

    # Publish for real
    python scripts/publish-modrinth.py --version 1.0.5 \\
        --changelog-file docs/release-notes-v1.0.5.md

Auth via MODRINTH_TOKEN env var or .env file. Falls back to ../StreamCraft/.env
if TBA's .env doesn't have MODRINTH_TOKEN. PAT scope: "Create version".
Get one at https://modrinth.com/settings/pats.

Idempotent: if a Modrinth version with the same version_number already exists,
the upload is skipped.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERR: requests not installed. Install with: pip install requests")
    sys.exit(1)


MODRINTH_API = "https://api.modrinth.com/v2"
PROJECT_SLUG = "theblockacademy"

# Game versions this build is compatible with. TBA targets 1.21.1 only.
GAME_VERSIONS = ["1.21.1"]

# Modrinth gets the Windows .mrpack only (see module docstring; never add the others here).
PLATFORMS = ["windows"]


def pack_loader() -> str:
    import re
    text = (Path(__file__).resolve().parent.parent / "pack.toml").read_text(encoding="utf-8")
    versions = text.split("[versions]", 1)[1]
    for loader in ("neoforge", "fabric", "forge", "quilt"):
        if re.search(rf"^{loader}\s*=", versions, re.M):
            return loader
    raise RuntimeError("no loader in pack.toml [versions]")


def filename_for(version: str, platform: str) -> str:
    suffix = "" if platform == "windows" else f"-{platform}"
    return f"TBA-{version}{suffix}.mrpack"


def load_dotenv(path: Path) -> None:
    """Minimal .env loader: KEY=VALUE per line, no quoting/expansion."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key and value and key not in os.environ:
            os.environ[key] = value


def resolve_project_id(slug: str, token: str) -> str:
    """Modrinth's POST /version requires the base62 project ID in the JSON body."""
    r = requests.get(
        f"{MODRINTH_API}/project/{slug}",
        headers={"Authorization": token},
        timeout=30,
    )
    if r.status_code == 404:
        raise SystemExit(f"ERR: Modrinth project '{slug}' not found.")
    r.raise_for_status()
    return r.json()["id"]


def find_existing_version(slug: str, version_number: str, token: str) -> str | None:
    r = requests.get(
        f"{MODRINTH_API}/project/{slug}/version",
        headers={"Authorization": token},
        timeout=30,
    )
    r.raise_for_status()
    for v in r.json():
        if v["version_number"] == version_number:
            return v["id"]
    return None


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--version", required=True, help="TBA pack version (e.g. 1.0.5)")
    p.add_argument(
        "--type",
        default="release",
        choices=["release", "beta", "alpha"],
    )
    p.add_argument(
        "--dist-dir",
        default="dist",
        help="Directory containing the 4 .mrpack files",
    )
    p.add_argument(
        "--changelog-file",
        required=True,
        help="Markdown file with the user-facing release notes",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print metadata without uploading",
    )
    args = p.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    # Try TBA's .env first, then StreamCraft's (where MODRINTH_TOKEN actually lives).
    load_dotenv(project_root / ".env")
    load_dotenv(project_root.parent / "StreamCraft" / ".env")

    token = os.environ.get("MODRINTH_TOKEN", "")
    if not token and not args.dry_run:
        print("ERR MODRINTH_TOKEN not set (env var, TBA/.env, or StreamCraft/.env)")
        return 1

    dist = (project_root / args.dist_dir).resolve()
    if not dist.is_dir():
        print(f"ERR dist dir not found: {dist}")
        return 1

    # Verify all 4 files exist before doing anything.
    files: list[tuple[str, Path]] = []
    missing: list[str] = []
    for plat in PLATFORMS:
        path = dist / filename_for(args.version, plat)
        if path.exists():
            files.append((plat, path))
        else:
            missing.append(path.name)
    if missing:
        print(f"ERR missing artifacts in {dist}:")
        for m in missing:
            print(f"  - {m}")
        print("Run: python scripts/build-variants.py")
        return 1

    changelog_path = (project_root / args.changelog_file).resolve()
    if not changelog_path.exists():
        print(f"ERR changelog file not found: {changelog_path}")
        return 1
    changelog = changelog_path.read_text(encoding="utf-8").strip()

    primary_filename = filename_for(args.version, "windows")
    metadata = {
        "name": f"v{args.version}",
        "version_number": args.version,
        "changelog": changelog,
        "dependencies": [],
        "game_versions": GAME_VERSIONS,
        "version_type": args.type,
        "loaders": [pack_loader()],
        "featured": False,
        # project_id is filled in below (resolve_project_id)
        "file_parts": [path.name for _, path in files],
        "primary_file": primary_filename,
    }

    print(f"Project:        {PROJECT_SLUG}")
    print(f"Version:        v{args.version} ({args.type})")
    print(f"Game versions:  {GAME_VERSIONS}")
    print(f"Files ({len(files)}):")
    total_mb = 0.0
    for plat, path in files:
        size_mb = path.stat().st_size / 1_000_000
        total_mb += size_mb
        marker = "  [primary]" if path.name == primary_filename else ""
        print(f"  {plat:14s} {path.name}  ({size_mb:.1f} MB){marker}")
    print(f"Total:          {total_mb:.1f} MB")
    print(f"Changelog:      {changelog_path.name} ({len(changelog)} chars)")

    import subprocess
    gate = subprocess.run([sys.executable, str(project_root / "scripts" / "audit-artifacts.py"),
                           *[str(path) for _, path in files]])
    if gate.returncode != 0:
        print("ERR: artifact gate failed; refusing to publish (Modrinth review would reject it)")
        return 1

    if args.dry_run:
        print(f"\nDRY-RUN metadata (project_id will be resolved at upload):")
        print(json.dumps(metadata, indent=2))
        return 0

    metadata["project_id"] = resolve_project_id(PROJECT_SLUG, token)
    print(f"\nResolved project ID: {metadata['project_id']}")

    existing = find_existing_version(PROJECT_SLUG, args.version, token)
    if existing:
        print(f"SKIP — v{args.version} already published (id={existing})")
        return 0

    # Modrinth's gateway chokes on multi-GB multipart bodies (connection aborts
    # silently around 1+ GB). Upload one file at a time:
    # 1. POST /version with metadata + Windows file (~475 MB)
    # 2. POST /version/{id}/file for each remaining variant
    windows_path = next(path for plat, path in files if plat == "windows")
    other_files = [(plat, path) for plat, path in files if plat != "windows"]

    metadata_for_first_post = dict(metadata)
    metadata_for_first_post["file_parts"] = [windows_path.name]
    metadata_for_first_post["primary_file"] = windows_path.name

    print(f"\nStep 1/{1 + len(other_files)}: POST /version with {windows_path.name} "
          f"({windows_path.stat().st_size / 1_000_000:.1f} MB) ...")
    with windows_path.open("rb") as fh:
        r = requests.post(
            f"{MODRINTH_API}/version",
            headers={"Authorization": token},
            files=[
                ("data", (None, json.dumps(metadata_for_first_post), "application/json")),
                (windows_path.name, (windows_path.name, fh, "application/octet-stream")),
            ],
            timeout=1800,
        )
    if r.status_code >= 400:
        print(f"FAILED on /version: Modrinth {r.status_code}: {r.text}")
        return 1
    data = r.json()
    version_id = data["id"]
    print(f"  OK version_id={version_id}, files={len(data.get('files', []))}")

    for i, (plat, path) in enumerate(other_files, start=2):
        print(f"\nStep {i}/{1 + len(other_files)}: POST /version/{version_id}/file "
              f"with {path.name} ({path.stat().st_size / 1_000_000:.1f} MB) ...")
        # Modrinth's /version/{id}/file expects multipart: one "file" part with the
        # binary, plus a "data" JSON part (file_types is required, others optional).
        with path.open("rb") as fh:
            r = requests.post(
                f"{MODRINTH_API}/version/{version_id}/file",
                headers={"Authorization": token},
                files=[
                    ("data", (None, json.dumps({"file_types": {path.name: None}}), "application/json")),
                    (path.name, (path.name, fh, "application/octet-stream")),
                ],
                timeout=1800,
            )
        if r.status_code >= 400:
            print(f"FAILED on /version/{version_id}/file ({plat}): Modrinth {r.status_code}: {r.text}")
            print(f"Version was created (id={version_id}) but missing some files. "
                  f"Add them manually or delete the version and re-run.")
            return 1
        print(f"  OK {plat} added")

    print(f"\nAll {len(files)} files uploaded.")
    print(f"URL: https://modrinth.com/modpack/{PROJECT_SLUG}/version/{args.version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
