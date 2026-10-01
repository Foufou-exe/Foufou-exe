#!/usr/bin/env python3
"""Sanity checks run by profile.timer before committing a refresh.

If anything looks broken (bad SVG, empty shelf, API hiccup...), exit 1 so the
workflow stops and yesterday's profile stays online.
"""
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
PANES = ["card", "docker", "trophies", "contrib"]
THEMES = ["dark", "light"]
MAX_KB = 600

errors = []


def check(ok, msg):
    print(f"  {'✓' if ok else '✗'} {msg}")
    if not ok:
        errors.append(msg)


def previous_stats():
    """stats.json as last committed, to catch regressions."""
    try:
        out = subprocess.run(["git", "show", "HEAD:assets/stats.json"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout
        return json.loads(out)
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError):
        return {}


def main():
    print("svg panes")
    svgs = {}
    for pane in PANES:
        for theme in THEMES:
            f = ASSETS / f"{pane}-{theme}.svg"
            if not f.exists():
                check(False, f"{f.name} missing")
                continue
            text = f.read_text(encoding="utf-8")
            svgs[f"{pane}-{theme}"] = text
            kb = len(text.encode()) / 1024
            try:
                root = ET.fromstring(text)
                valid = root.tag.endswith("svg") and float(root.get("height", 0)) > 0
            except ET.ParseError as e:
                valid = False
                print(f"    {e}")
            check(valid, f"{f.name} is valid SVG")
            check(kb <= MAX_KB, f"{f.name} {kb:.0f} KB ≤ {MAX_KB} KB")

    print("content")
    stats_file = ASSETS / "stats.json"
    if not stats_file.exists():
        check(False, "stats.json missing")
        return
    s = json.loads(stats_file.read_text())
    prev = previous_stats()

    check(s["repos"] > 0, f"repos: {s['repos']}")
    check(s["commits"] > 0, f"commits: {s['commits']}")
    check(len(s["projects"]) > 0, f"docker ps: {len(s['projects'])} containers")
    check(len(s["achievements"]) > 0, f"shelf: {len(s['achievements'])} achievements")
    check(s["graph_3d"], "3D contribution graph rendered")

    # achievements are never lost: fewer than last time means the scraper broke
    lost = set(prev.get("achievements", [])) - set(s["achievements"])
    check(not lost, f"no achievement lost{f' (missing: {sorted(lost)})' if lost else ''}")
    if prev.get("commits"):
        check(s["commits"] >= prev["commits"] * 0.9, f"commits didn't collapse ({prev['commits']} → {s['commits']})")

    for theme in THEMES:
        icons = svgs.get(f"trophies-{theme}", "").count("data:image/png;base64,")
        check(icons == len(s["achievements"]), f"trophies-{theme}: {icons} icons for {len(s['achievements'])} achievements")
        rows = sum(f">{name}" in svgs.get(f"docker-{theme}", "") for name in s["projects"])
        check(rows == len(s["projects"]), f"docker-{theme}: {rows} rows for {len(s['projects'])} projects")
        check("data:image/svg+xml;base64," in svgs.get(f"contrib-{theme}", ""), f"contrib-{theme}: 3D graph embedded")


if __name__ == "__main__":
    main()
    if errors:
        for e in errors:
            print(f"::error title=profile check::{e}")
        print(f"\n{len(errors)} check(s) failed, nothing will be committed.")
        sys.exit(1)
    print("\nall checks passed")
