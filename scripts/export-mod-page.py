#!/usr/bin/env python3
"""Write the data file behind theblock.academy/tba/mods: every mod, resource pack and shader in the pack.

The pack's own entries (mods/, resourcepacks/, shaderpacks/ *.pw.toml) are the list. Each is filled from:
  docs/CREDITS.md   section, link, author(s), version, donate link (matched by store slug, then name)
  README.md         the one-line "what it does" written for the pack (preferred description)
  store APIs        Modrinth / cfwidget summary, authors and link for anything the docs don't cover

    py -3 scripts/export-mod-page.py [--out ../theblockacademy/src/data/tba-mods.json]

Re-run after each release that changes the pack, then commit the JSON in theblockacademy.
"""
from __future__ import annotations

import argparse, json, re, sys, tomllib, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT.parent / "theblockacademy" / "src" / "data" / "tba-mods.json"
UA = {"User-Agent": "tba-mod-page (modpack maintenance script)"}
SKIP_SECTIONS = {"How to Support These Creators", "Special Thanks", "Creator Highlights"}
LINKED = re.compile(r"^\|\s*\[(?P<name>.+?)\]\((?P<url>https?://[^)\s]+)\)\s*\|(?P<rest>.*)\|\s*$")
PLAIN = re.compile(r"^\|\s*(?P<name>[^|\[]+?)\s*\|(?P<rest>.*)\|\s*$")
LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
DIR_SECTION = {"resourcepacks": "Resource Packs", "shaderpacks": "Shaders"}
# CREDITS section -> page section
SECTION = {"Bundled Shaders": "Shaders", "Library/API": "Libraries", "Server-Only": "Server",
           "Map": "Maps", "Seasons & Visuals": "Visuals"}


def norm(s: str) -> str:
    s = re.sub(r"\[(fabric|forge|neoforge|fabric & forge|emf|etf)\]", "", s.lower())
    return re.sub(r"[^a-z0-9]", "", s)


def slug_of(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1].lower() if url else ""


def get_json(url: str):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return json.load(r)


def credits_rows() -> list[dict]:
    rows, section = [], ""
    for line in (ROOT / "docs" / "CREDITS.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            section = line[3:].strip().removesuffix(" Mods").strip()
            continue
        if section in SKIP_SECTIONS or not line.startswith("|") or set(line) <= set("|- "):
            continue
        m = LINKED.match(line) or PLAIN.match(line)
        if not m or m.group("name").strip() in {"Mod", "Pack", "Shader"}:
            continue
        cells = [c.strip() for c in m.group("rest").split("|")]
        donate = LINK.search(cells[-1]) if cells else None
        url = m.groupdict().get("url") or ""
        rows.append({"section": SECTION.get(section, section), "name": m.group("name").strip(), "url": url,
                     "authors": cells[0] if cells else "",
                     "version": cells[1] if len(cells) > 2 else "",
                     "donate": donate.group(2) if donate else ""})
    return rows


def readme_descriptions() -> dict[str, str]:
    out = {}
    for line in (ROOT / "README.md").read_text(encoding="utf-8").splitlines():
        if line.lower().startswith("### left behind"):
            break
        m = re.match(r"- \*\*(.+?)\*\*\s*[-–—]\s*(.+)$", line)
        if m:
            out[norm(m.group(1))] = m.group(2).strip()
    return out


def pack_entries() -> list[dict]:
    out = []
    for d in ("mods", "resourcepacks", "shaderpacks"):
        for p in sorted((ROOT / d).glob("*.pw.toml")):
            t = tomllib.loads(p.read_text(encoding="utf-8"))
            upd = t.get("update", {})
            mr_id = upd.get("modrinth", {}).get("mod-id")
            mr = ROOT / "scripts" / "mr-sources" / d / p.name
            if not mr_id and mr.exists():
                mr_id = tomllib.loads(mr.read_text(encoding="utf-8")).get("update", {}).get("modrinth", {}).get("mod-id")
            out.append({"key": p.name[:-len(".pw.toml")], "dir": d, "name": t["name"],
                        "side": t.get("side", "both"),
                        "cf_id": upd.get("curseforge", {}).get("project-id"), "mr_id": mr_id})
    return out


def find(name: str, table: dict):
    n = norm(name)
    if n in table:
        return table[n]
    hits = [v for k, v in table.items() if k and len(k) > 4 and (k.startswith(n) or n.startswith(k))]
    return hits[0] if len(hits) == 1 else None


def clean_name(name: str) -> str:
    name = re.sub(r"\s*\[(Fabric|Forge|NeoForge|Fabric & Forge)\]\s*", " ", name)
    name = re.sub(r"\s*\((?:Neo)?Forge(?:\s*[/&]\s*(?:Neo)?Forge)?\)\s*", " ", name, flags=re.I)  # "(NeoForge/Forge)"
    name = re.sub(r"\s+(?:Fabric|Forge|NeoForge)(?:/(?:Fabric|Forge|NeoForge))+\b", "", name)  # "Fabric/Forge/NeoForge"
    return re.sub(r"\s{2,}", " ", name).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    a = ap.parse_args()

    version = re.search(r'^version = "(.*)"$', (ROOT / "pack.toml").read_text(encoding="utf-8"), re.M).group(1)
    credits, descs, entries = credits_rows(), readme_descriptions(), pack_entries()
    by_slug = {slug_of(c["url"]): c for c in credits if c["url"]}
    by_name = {norm(c["name"]): c for c in credits}

    # store data for every entry (summary, authors, link): Modrinth in bulk, cfwidget per project
    mr_ids = sorted({e["mr_id"] for e in entries if e["mr_id"]})
    mr = {}
    for i in range(0, len(mr_ids), 80):
        q = urllib.parse.quote(json.dumps(mr_ids[i:i + 80]))
        for p in get_json(f"https://api.modrinth.com/v2/projects?ids={q}"):
            mr[p["id"]] = mr[p["slug"]] = p

    out, used, report = [], set(), []
    for e in entries:
        c = by_slug.get(e["key"]) or find(e["name"], by_name)
        if c:
            used.add(id(c))
        desc = find(e["name"], descs) or (find(c["name"], descs) if c else None) or ""
        p = mr.get(e["mr_id"] or "")
        cfw = None
        if e["cf_id"] and (not desc or not c):
            try:
                cfw = get_json(f"https://api.cfwidget.com/{e['cf_id']}")
            except Exception:  # noqa: BLE001 - store data is a fallback only
                cfw = None
        if not desc:
            desc = (p or {}).get("description") or (cfw or {}).get("summary") or ""
        url = (c or {}).get("url") or ""
        if not url:
            url = (f"https://www.curseforge.com/minecraft/{ {'mods': 'mc-mods', 'resourcepacks': 'texture-packs', 'shaderpacks': 'shaders'}[e['dir']] }/{cfw['urls']['curseforge'].rsplit('/', 1)[-1]}"
                   if cfw and cfw.get("urls") else f"https://modrinth.com/project/{p['slug']}" if p else "")
        authors = (c or {}).get("authors") or ", ".join(m["username"] for m in (cfw or {}).get("members", [])[:3])
        if not authors and p:
            try:
                authors = ", ".join(m["user"]["username"] for m in get_json(f"https://api.modrinth.com/v2/project/{p['id']}/members")
                                    if m.get("role", "").lower() == "owner" or len(authors) == 0)[:120]
            except Exception:  # noqa: BLE001
                authors = ""
        section = (c or {}).get("section") or DIR_SECTION.get(e["dir"], "Other")
        if e["dir"] == "shaderpacks":
            section = "Shaders"
        out.append({"key": e["key"], "name": clean_name((c or {}).get("name") or e["name"]), "section": section,
                    "side": e["side"], "description": desc, "authors": authors, "url": url,
                    "version": (c or {}).get("version", ""), "donate": (c or {}).get("donate", "")})
        if not c:
            report.append(f"not in CREDITS: {e['dir']}/{e['key']}")
        if not desc:
            report.append(f"no description: {e['key']}")
    for c in credits:
        if id(c) not in used:
            report.append(f"CREDITS row with no pack entry: {c['name']}")

    data = {"version": version, "count": sum(e["dir"] == "mods" for e in entries),
            "resourcePacks": sum(e["dir"] == "resourcepacks" for e in entries),
            "shaders": sum(e["dir"] == "shaderpacks" for e in entries), "entries": out}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"{a.out}: {len(out)} entries ({data['count']} mods, {data['resourcePacks']} resource packs, "
          f"{data['shaders']} shaders), TBA {version}")
    for r in report:
        print("  " + r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
