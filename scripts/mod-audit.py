#!/usr/bin/env python3
"""Generate docs/mod-audit.md: one row per mod in the pack, for a hand audit (keep / remove / replace).

Per mod: side, source, version file, licence and one-line summary (Modrinth API for every mod that
has a Modrinth copy, via mods/ or scripts/mr-sources/; cfwidget for CurseForge-only mods), the
README category, which pack mods require it and which mods it requires (read from each jar's
META-INF/neoforge.mods.toml), plus the existing Decision/Note columns of a previous audit, kept so a
re-run doesn't wipe the owner's decisions.

The jars are not in the repo: pass folders that hold them (an installed instance's mods/, a test
server's mods/). Jars are matched to entries by file name.

    py -3 scripts/mod-audit.py --jars ../TBA2/v201-test/mods --jars <client mods dir>
"""
from __future__ import annotations

import argparse, json, re, sys, tomllib, urllib.request, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "mod-audit.md"
UA = {"User-Agent": "tba-mod-audit (modpack maintenance script)"}
# mod ids every NeoForge mod lists; not pack entries
PLATFORM_IDS = {"minecraft", "neoforge", "forge", "java"}
JIJ_IDS = {"kotlin-for-forge": ["kotlinforforge"]}


def get_json(url: str):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return json.load(r)


def load_entries() -> list[dict]:
    out = []
    for p in sorted((ROOT / "mods").glob("*.pw.toml")):
        t = tomllib.loads(p.read_text(encoding="utf-8"))
        upd = t.get("update", {})
        e = {"key": p.name[:-len(".pw.toml")], "name": t["name"], "file": t["filename"],
             "side": t.get("side", "both"),
             "source": "CurseForge" if "curseforge" in upd else "Modrinth" if "modrinth" in upd else "URL",
             "cf_id": upd.get("curseforge", {}).get("project-id"),
             "mr_id": upd.get("modrinth", {}).get("mod-id")}
        mr = ROOT / "scripts" / "mr-sources" / "mods" / p.name
        if not e["mr_id"] and mr.exists():
            e["mr_id"] = tomllib.loads(mr.read_text(encoding="utf-8")).get("update", {}).get("modrinth", {}).get("mod-id")
        out.append(e)
    return out


def readme_categories() -> dict[str, str]:
    cats, cur = {}, ""
    for line in (ROOT / "README.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("### "):
            cur = line[4:].strip()
            if cur.lower().startswith("left behind"):  # removed mods, not a category
                break
        m = re.match(r"- \*\*(.+?)\*\*", line)
        if m and cur:
            cats[norm(m.group(1))] = cur
    return cats


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def jar_meta(path: Path) -> tuple[list[str], list[tuple[str, str]]]:
    """(mod ids the jar provides, [(dependency mod id, type)])."""
    try:
        with zipfile.ZipFile(path) as z:
            raw = z.read("META-INF/neoforge.mods.toml").decode("utf-8", "replace")
    except (KeyError, zipfile.BadZipFile):
        return [], []
    try:
        t = tomllib.loads(raw)
    except tomllib.TOMLDecodeError:
        ids = re.findall(r'^\s*modId\s*=\s*"([^"]+)"', raw, re.M)
        return ids[:1], []
    ids = [m.get("modId") for m in t.get("mods", []) if m.get("modId")]
    deps = []
    if t.get("modLoader") == "kotlinforforge":  # a language loader, not a [[dependencies]] entry
        deps.append(("kotlinforforge", "required"))
    for lst in (t.get("dependencies") or {}).values():
        for d in lst:
            # three spellings in the wild: type="required" (NeoForge), mandatory=true (Forge), required=true
            kind = d.get("type") or ("required" if d.get("mandatory") or d.get("required") else "optional")
            deps.append((d.get("modId"), str(kind).lower()))
    return ids, deps


def previous_columns() -> dict[str, tuple[str, str]]:
    """key -> (decision, note) from an existing audit, so re-runs keep hand edits."""
    if not OUT.exists():
        return {}
    keep = {}
    for line in OUT.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 10 and cells[1].startswith("`"):
            keep[cells[1].strip("`")] = (cells[-2], cells[-1])
    return keep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jars", action="append", default=[], help="folder holding the pack's jars")
    a = ap.parse_args()

    entries = load_entries()
    jars = {}
    for d in a.jars:
        for j in Path(d).glob("*.jar"):
            jars.setdefault(j.name, j)
    by_id, deps_of = {}, {}
    for e in entries:
        j = jars.get(e["file"])
        ids, deps = jar_meta(j) if j else ([], [])
        e["have_jar"] = bool(j)
        # container jars whose real mod is jar-in-jar (no neoforge.mods.toml at the top level)
        ids = ids or JIJ_IDS.get(e["key"], [])
        for i in ids:
            by_id[i] = e["key"]
        deps_of[e["key"]] = deps
    requires = {e["key"]: sorted({by_id[d] for d, k in deps_of[e["key"]]
                                  if k == "required" and d in by_id and by_id[d] != e["key"]})
                for e in entries}
    required_by = {e["key"]: [] for e in entries}
    for k, rs in requires.items():
        for r in rs:
            required_by[r].append(k)

    # summaries: Modrinth in bulk, cfwidget for the rest
    mr_ids = sorted({e["mr_id"] for e in entries if e["mr_id"]})
    info = {}
    for i in range(0, len(mr_ids), 80):
        q = urllib.parse.quote(json.dumps(mr_ids[i:i + 80]))
        for p in get_json(f"https://api.modrinth.com/v2/projects?ids={q}"):
            info[p["id"]] = (p.get("description", ""), (p.get("license") or {}).get("id", ""))
            info[p["slug"]] = info[p["id"]]
    cats = readme_categories()
    prev = previous_columns()

    rows = []
    for e in entries:
        summary, lic = info.get(e["mr_id"], ("", "")) if e["mr_id"] else ("", "")
        if not summary and e["cf_id"]:
            try:
                w = get_json(f"https://api.cfwidget.com/{e['cf_id']}")
                summary, lic = w.get("summary", ""), w.get("license", "") or lic
            except Exception as ex:  # noqa: BLE001 - a missing summary is not fatal
                summary = f"(cfwidget: {ex.__class__.__name__})"
        cat = cats.get(norm(e["name"]), "")
        if not cat:
            cat = next((c for n, c in cats.items() if n and (n in norm(e["name"]) or norm(e["name"]) in n)), "")
        flags = []
        if not e["have_jar"]:
            flags.append("jar not scanned")
        if required_by[e["key"]] and not cat:
            flags.append("library")
        decision, note = prev.get(e["key"], ("", ""))
        rows.append("| " + " | ".join([
            e["name"].replace("|", "/"), f"`{e['key']}`", e["side"], e["source"], lic or "?",
            cat or "-", (summary or "").replace("|", "/").replace("\n", " ")[:140],
            ", ".join(required_by[e["key"]]) or "-",
            ", ".join(requires[e["key"]]) + (f" ({'; '.join(flags)})" if flags else "") or "-",
            decision, note]) + " |")

    head = [
        "# TBA mod audit",
        "",
        f"{len(entries)} mods in `mods/`. Generated by `scripts/mod-audit.py`; the **Decision** and "
        "**Note** columns are hand-edited and survive a re-run. Decision: keep / remove / replace.",
        "A mod listed under *Required by* can only go when those go too.",
        "",
        "| Mod | Entry | Side | Source | Licence | README section | What it does | Required by | Requires | Decision | Note |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    OUT.write_text("\n".join(head + rows) + "\n", encoding="utf-8", newline="\n")
    missing = sum(not e["have_jar"] for e in entries)
    print(f"{OUT.relative_to(ROOT)}: {len(rows)} rows ({missing} without a scanned jar)")
    return 0


if __name__ == "__main__":
    import urllib.parse  # noqa: E402
    sys.exit(main())
