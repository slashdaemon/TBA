#!/usr/bin/env python3
"""
Build per-platform TBA modpack variants.

StreamCraft ships platform-specific JARs (Windows, Linux, macOS-arm64,
macOS-x86_64) because of native LiveKit FFI / JavaCV / JNA dependencies.
Packwiz pins one CurseForge file ID per mod, so each platform needs its
own modpack export with the matching StreamCraft JAR.

Usage:
    python scripts/build-variants.py                       # build all platforms
    python scripts/build-variants.py --platform windows    # one platform
    python scripts/build-variants.py --version 1.0.4       # override pack.toml
    python scripts/build-variants.py --streamcraft 0.7.26+mc1.21.1

Output: dist/TBA-<version>[-<platform>].{mrpack,zip}
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKWIZ = REPO_ROOT / "packwiz.exe"
STREAMCRAFT_TOML = REPO_ROOT / "mods" / "streamcraft-live.pw.toml"
PACK_TOML = REPO_ROOT / "pack.toml"
DIST = REPO_ROOT / "dist"

# Windows is canonical (no classifier in filename); other platforms get a suffix.
PLATFORMS = ["windows", "linux", "macos-arm64", "macos-x86_64"]


@dataclass(frozen=True)
class StreamCraftFile:
    """A registered StreamCraft artifact: the CurseForge file (cf_file_id) and/or the same file
    on Modrinth (mr_url + mr_filename + mr_sha512). The .zip always uses the CurseForge file; the
    .mrpack uses the Modrinth URL when registered (a CurseForge file would be bundled as an
    override jar, which Modrinth's review rejects)."""
    filename: str
    sha1: str
    cf_file_id: int | None = None
    mr_url: str | None = None
    mr_filename: str | None = None
    mr_sha512: str | None = None

    def __post_init__(self) -> None:
        if self.cf_file_id is None and self.mr_url is None:
            raise ValueError(f"StreamCraftFile {self.filename}: set cf_file_id and/or mr_url")


MR_SC_BASE = "https://cdn.modrinth.com/data/UUUunIAe/versions"


# Registry of StreamCraft files per version + platform.
#
# CurseForge mode (preferred — CurseForge-First Policy):
#   StreamCraftFile(filename=..., sha1=..., cf_file_id=NNNNNNN)
#
# Modrinth URL mode (fallback when CF approval is pending or unavailable):
#   StreamCraftFile(filename=..., sha1=..., mr_url="https://cdn.modrinth.com/...")
#   When using mr_url, mrpack4server needs `cdn.modrinth.com` in
#   whitelisted_domains (server-config.py update_modpack_info handles this).
#
# When CurseForge later approves a Modrinth-pinned version, swap the entry to
# cf_file_id mode so we're back on CF for downstream CurseForge App users.
STREAMCRAFT_REGISTRY: dict[str, dict[str, StreamCraftFile]] = {
    "0.6.2+mc1.21.1": {
        "windows": StreamCraftFile(
            filename="streamcraft-0.6.2+mc1.21.1.jar",
            sha1="681de053207181b5672da0cba78696fa71f58390",
            cf_file_id=7952947,
        ),
    },
    "0.7.26+mc1.21.1": {
        "windows": StreamCraftFile(
            filename="streamcraft-0.7.26+mc1.21.1.jar",
            sha1="69c5de6703750e88e0fffee9d74e0ad6cad141df",
            cf_file_id=7996534,
        ),
        "linux": StreamCraftFile(
            filename="streamcraft-0.7.26+mc1.21.1-linux.jar",
            sha1="e0b4e084263b54cdcffe49a6b7867a66f9746d72",
            cf_file_id=7996556,
        ),
        "macos-arm64": StreamCraftFile(
            filename="streamcraft-0.7.26+mc1.21.1-macos-arm64.jar",
            sha1="bdaae7d1b1097488326bbdb7ffda8dc409ffaa27",
            cf_file_id=7996538,
        ),
        "macos-x86_64": StreamCraftFile(
            filename="streamcraft-0.7.26+mc1.21.1-macos-x86_64.jar",
            sha1="3a85e944b38260ff573f7bef8da55f6229a5b65e",
            cf_file_id=7996545,
        ),
    },
    "0.8.25+mc1.21.1": {
        "windows": StreamCraftFile(
            filename="streamcraft-0.8.25+mc1.21.1.jar",
            sha1="b9dd7d132508566c2b3d1b0b1c42185941134b11",
            cf_file_id=8124065,
        ),
        "linux": StreamCraftFile(
            filename="streamcraft-0.8.25+mc1.21.1-linux.jar",
            sha1="701dc95e1d2080f5c48bd31841a8f4ae316bffcc",
            cf_file_id=8124066,
        ),
        "macos-arm64": StreamCraftFile(
            filename="streamcraft-0.8.25+mc1.21.1-macos-arm64.jar",
            sha1="92a93cb03065ab2af25e773d2257fde7832aa86d",
            cf_file_id=8124068,
        ),
        "macos-x86_64": StreamCraftFile(
            filename="streamcraft-0.8.25+mc1.21.1-macos-x86_64.jar",
            sha1="2fd599a4c75dd012ec8865c8d0543c5ee8d1b816",
            cf_file_id=8124069,
        ),
    },
    "0.33.0+mc1.21.1": {
        "windows": StreamCraftFile(
            filename="streamcraft-pc-0.33.0-mc1.21.1-cf.jar",
            sha1="46ecb6b729aaaa897eb3bc5b3b687cd25b044747",
            cf_file_id=9445720,
        ),
        "linux": StreamCraftFile(
            filename="streamcraft-linux-x64-0.33.0-mc1.21.1-cf.jar",
            sha1="dbaac0062767f6b785a4da44fa7b8f993040f950",
            cf_file_id=9445725,
        ),
        "macos-arm64": StreamCraftFile(
            filename="streamcraft-mac-arm64-0.33.0-mc1.21.1-cf.jar",
            sha1="fafabaadd496fb829b1006e345fe2c03f72f5d7a",
            cf_file_id=9445722,
        ),
        "macos-x86_64": StreamCraftFile(
            filename="streamcraft-mac-x64-0.33.0-mc1.21.1-cf.jar",
            sha1="da28b3e34cd22cd5465a8cd39fdf62b0ebb64142",
            cf_file_id=9445724,
        ),
    },
    # TBA 2.0.0+ runs NeoForge 1.21.1.
    # Modrinth version cD7cUqAn holds byte-identical copies (same sha1) of the CurseForge files.
    "0.33.0+mc1.21.1-neoforge": {
        "windows": StreamCraftFile(
            filename="streamcraft-pc-0.33.0-mc1.21.1-neoforge-cf.jar",
            sha1="4fbf6f367eb694afb430d95540c3e17c93346785",
            cf_file_id=9445871,
            mr_url=f"{MR_SC_BASE}/cD7cUqAn/streamcraft-pc-0.33.0%2Bmc1.21.1-neoforge.jar",
            mr_filename="streamcraft-pc-0.33.0+mc1.21.1-neoforge.jar",
            mr_sha512="03135afe2139047d4aa3769cfe65e0b124a0092b4c885eb59bf81805a18ddf296affc1d90ad4a8831fc49aa55636cc0f9435eadf2fc29d85b2eaf5d3f83ba0ab",
        ),
        "linux": StreamCraftFile(
            filename="streamcraft-linux-x64-0.33.0-mc1.21.1-neoforge-cf.jar",
            sha1="727970610a4f553a3b2a13e1b0a89045f761c0cd",
            cf_file_id=9445875,
            mr_url=f"{MR_SC_BASE}/cD7cUqAn/streamcraft-linux-x64-0.33.0%2Bmc1.21.1-neoforge.jar",
            mr_filename="streamcraft-linux-x64-0.33.0+mc1.21.1-neoforge.jar",
            mr_sha512="75abb72edfc037d22cfc7dc947ff11f315225ceab3ff401d4af7d0c6490ec9e31ba5556ebc95bf29fd33a59740cf3734b325e858a3345dae3d573c1d04a2df76",
        ),
        "macos-arm64": StreamCraftFile(
            filename="streamcraft-mac-arm64-0.33.0-mc1.21.1-neoforge-cf.jar",
            sha1="a2cf47f26c17856f9f2eafa07288c13ff7047b4f",
            cf_file_id=9445872,
            mr_url=f"{MR_SC_BASE}/cD7cUqAn/streamcraft-mac-arm64-0.33.0%2Bmc1.21.1-neoforge.jar",
            mr_filename="streamcraft-mac-arm64-0.33.0+mc1.21.1-neoforge.jar",
            mr_sha512="484b270e7386febb540e5aac57593a07d4986feadbddbc4649b35025027669bca6147ed74d8411a20f801b28ca0da02e4b2b0207056b0573387f228132e5d39f",
        ),
        "macos-x86_64": StreamCraftFile(
            filename="streamcraft-mac-x64-0.33.0-mc1.21.1-neoforge-cf.jar",
            sha1="088f3d49e0fe81950be8f6c769015ee22f1782a5",
            cf_file_id=9445874,
            mr_url=f"{MR_SC_BASE}/cD7cUqAn/streamcraft-mac-x64-0.33.0%2Bmc1.21.1-neoforge.jar",
            mr_filename="streamcraft-mac-x64-0.33.0+mc1.21.1-neoforge.jar",
            mr_sha512="be6af31149a3b845c8e10518a3dba3aa9321b2fb5f9fd1bcb85e83489d7c2091d5bf0bd12ac9b2a3d4ec43a938dfe36243f3af93691b2a1767f9029e11811196",
        ),
    },
}


def read_pack_version() -> str:
    for line in PACK_TOML.read_text(encoding="utf-8").splitlines():
        if line.startswith("version"):
            return line.split("=", 1)[1].strip().strip('"')
    raise RuntimeError("Could not parse version from pack.toml")


def read_current_streamcraft_version() -> str:
    """Infer the StreamCraft version currently pinned in mods/streamcraft-live.pw.toml.

    Returns the registry key (e.g., '0.6.2+mc1.21.1') by matching the filename.
    """
    text = STREAMCRAFT_TOML.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("filename"):
            filename = line.split("=", 1)[1].strip().strip('"')
            for key, variants in STREAMCRAFT_REGISTRY.items():
                for v in variants.values():
                    if v.filename == filename:
                        return key
    raise RuntimeError(
        f"Cannot infer StreamCraft version from {STREAMCRAFT_TOML}. "
        "Pass --streamcraft <version> explicitly."
    )


def write_streamcraft_toml(file: StreamCraftFile, store: str = "curseforge") -> None:
    """store="curseforge": CurseForge metadata (the .zip, and the canonical pack).
    store="modrinth": the Modrinth URL when registered, else falls back to CurseForge."""
    if store == "modrinth" and file.mr_url is not None and file.mr_sha512 is not None:
        body = f'''name = "StreamCraft Live"
filename = "{file.mr_filename or file.filename}"
side = "both"

[download]
url = "{file.mr_url}"
hash-format = "sha512"
hash = "{file.mr_sha512}"
'''
    elif file.cf_file_id is not None:
        body = f'''name = "StreamCraft Live"
filename = "{file.filename}"
side = "both"

[download]
hash-format = "sha1"
hash = "{file.sha1}"
mode = "metadata:curseforge"

[update]
[update.curseforge]
file-id = {file.cf_file_id}
project-id = 1451729
'''
    else:
        body = f'''name = "StreamCraft Live"
filename = "{file.filename}"
side = "both"

[download]
hash-format = "sha1"
hash = "{file.sha1}"
url = "{file.mr_url}"
'''
    STREAMCRAFT_TOML.write_text(body, encoding="utf-8")


def run(cmd: list[str]) -> None:
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise RuntimeError(f"Command failed: {' '.join(cmd)}")


# Per-store source layers (same mechanism as TBS-client's scripts/publish.py).
# The canonical pack is CurseForge-first. Each store's export overlays its own layer, mirroring
# the pack layout, so every entry is a store reference instead of a bundled file:
#   scripts/cf-sources/  hand-made CurseForge entries for the few Modrinth-canonical files
#   scripts/mr-sources/  Modrinth entries for every CurseForge file, generated by
#                        scripts/sync-mr-sources.py (must be current; checked before building)
# CurseForge rejects bundled jars of CurseForge-hosted projects; Modrinth rejects bundled files
# that are on Modrinth or that we have no right to redistribute. Entries in *_EXCLUDED are left
# out of that store's export: files on neither store whose licence forbids redistribution.
CF_SOURCES = REPO_ROOT / "scripts" / "cf-sources"
MR_SOURCES = REPO_ROOT / "scripts" / "mr-sources"
CF_EXCLUDED = {
    "resourcepacks/unobtrusive-weather.pw.toml": "Modrinth-only, All Rights Reserved",
    "shaderpacks/mello.pw.toml": "Modrinth-only, All Rights Reserved",
}
MR_EXCLUDED: dict[str, str] = {}
LAYERS = {
    "curseforge": (CF_SOURCES, CF_EXCLUDED),
    "modrinth": (MR_SOURCES, MR_EXCLUDED),
}


def check_layers() -> None:
    """Fail before touching the pack: orphan swaps, unknown exclusions, stale Modrinth layer."""
    problems = []
    for store, (src_dir, excluded) in LAYERS.items():
        for src in sorted(src_dir.rglob("*.pw.toml")) if src_dir.exists() else []:
            rel = src.relative_to(src_dir).as_posix()
            if not (REPO_ROOT / rel).exists():
                problems.append(f"orphan {store} swap {src.relative_to(REPO_ROOT).as_posix()} "
                                f"(no canonical {rel}): delete it or restore the entry")
        for rel in excluded:
            if not (REPO_ROOT / rel).exists():
                problems.append(f"{store} exclusion {rel} has no canonical entry")
    r = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "sync-mr-sources.py"), "--check"],
                       cwd=REPO_ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        problems.append("Modrinth layer out of date (run: py -3 scripts/sync-mr-sources.py):\n      "
                        + r.stdout.strip().replace("\n", "\n      "))
    if problems:
        raise SystemExit("ERR: store layer problem(s):\n  " + "\n  ".join(problems))


def export_for_store(store: str) -> None:
    """Overlay the store's layer, export, then restore the canonical pack (even on failure)."""
    src_dir, excluded = LAYERS[store]
    saved: dict[Path, bytes | None] = {}
    try:
        for rel in excluded:
            canon = REPO_ROOT / rel
            saved[canon] = canon.read_bytes()
            canon.unlink()
        swaps = sorted(src_dir.rglob("*.pw.toml")) if src_dir.exists() else []
        for src in swaps:
            canon = REPO_ROOT / src.relative_to(src_dir)
            if canon in saved:
                continue
            saved[canon] = canon.read_bytes()
            shutil.copyfile(src, canon)
        print(f"  ({store}: {len(swaps)} swapped, {len(excluded)} excluded)")
        run([str(PACKWIZ), "refresh"])
        run([str(PACKWIZ), store, "export"])
    finally:
        for canon, data in saved.items():
            if data is not None:
                canon.write_bytes(data)
        run([str(PACKWIZ), "refresh"])


def build_one(platform: str, pack_version: str, sc_version: str) -> None:
    if platform not in STREAMCRAFT_REGISTRY[sc_version]:
        raise RuntimeError(
            f"StreamCraft {sc_version} has no '{platform}' variant in the registry. "
            f"Available: {sorted(STREAMCRAFT_REGISTRY[sc_version])}"
        )

    suffix = "" if platform == "windows" else f"-{platform}"
    sc_file = STREAMCRAFT_REGISTRY[sc_version][platform]

    print(f"\n=== Building {platform} (StreamCraft {sc_file.filename}) ===")
    write_streamcraft_toml(sc_file, "modrinth")
    export_for_store("modrinth")
    write_streamcraft_toml(sc_file, "curseforge")
    export_for_store("curseforge")

    # Packwiz writes <pack-name>-<version>.{mrpack,zip} to repo root.
    src_mrpack = REPO_ROOT / f"TBA-{pack_version}.mrpack"
    src_zip = REPO_ROOT / f"TBA-{pack_version}.zip"
    dst_mrpack = DIST / f"TBA-{pack_version}{suffix}.mrpack"
    dst_zip = DIST / f"TBA-{pack_version}{suffix}.zip"

    DIST.mkdir(exist_ok=True)
    shutil.move(str(src_mrpack), str(dst_mrpack))
    shutil.move(str(src_zip), str(dst_zip))
    print(f"  -> {dst_mrpack.name}")
    print(f"  -> {dst_zip.name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--platform",
        choices=PLATFORMS,
        help="Build only this platform (default: all four).",
    )
    parser.add_argument(
        "--version",
        help="Override pack version (default: read from pack.toml).",
    )
    parser.add_argument(
        "--streamcraft",
        help="StreamCraft registry key (e.g., '0.7.26+mc1.21.1'). "
             "Default: infer from current mods/streamcraft-live.pw.toml.",
    )
    args = parser.parse_args()

    if not PACKWIZ.exists():
        print(f"error: {PACKWIZ} not found", file=sys.stderr)
        return 1

    pack_version = args.version or read_pack_version()
    sc_version = args.streamcraft or read_current_streamcraft_version()

    if sc_version not in STREAMCRAFT_REGISTRY:
        print(
            f"error: StreamCraft '{sc_version}' not in registry. "
            f"Known: {sorted(STREAMCRAFT_REGISTRY)}",
            file=sys.stderr,
        )
        return 1

    platforms = [args.platform] if args.platform else PLATFORMS
    # Skip platforms missing from this StreamCraft version's registry, with a warning.
    available = []
    for p in platforms:
        if p in STREAMCRAFT_REGISTRY[sc_version]:
            available.append(p)
        else:
            print(f"warn: skipping {p} (no StreamCraft {sc_version} file registered)")
    if not available:
        print("error: no platforms to build", file=sys.stderr)
        return 1

    print(f"Pack version:       {pack_version}")
    print(f"StreamCraft:        {sc_version}")
    print(f"Platforms to build: {', '.join(available)}")

    check_layers()
    original_toml = STREAMCRAFT_TOML.read_text(encoding="utf-8")
    try:
        for platform in available:
            build_one(platform, pack_version, sc_version)
    finally:
        STREAMCRAFT_TOML.write_text(original_toml, encoding="utf-8")
        run([str(PACKWIZ), "refresh"])
        print(f"\nRestored {STREAMCRAFT_TOML.name} to original.")

    # Store-compliance gate over everything just built.
    built = [DIST / f"TBA-{pack_version}{'' if p == 'windows' else '-' + p}.{ext}"
             for p in available for ext in ("mrpack", "zip")]
    gate = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "audit-artifacts.py"),
                           *map(str, built)], cwd=REPO_ROOT)
    if gate.returncode != 0:
        print("\nERROR: artifact gate failed; do not publish these files.", file=sys.stderr)
        return 1
    print(f"\nDone. Artifacts in {DIST}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
