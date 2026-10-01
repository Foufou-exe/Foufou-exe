#!/usr/bin/env python3
"""Generate the fastfetch-style profile card (dark + light SVG).

Stdlib only. Uses GITHUB_TOKEN (GraphQL) when available, falls back to the
public REST API otherwise.
"""
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

USER = "Foufou-exe"
OUT = Path(__file__).resolve().parent.parent / "assets"
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")

THEMES = {
    "dark": dict(bg="#0d1117", bar="#161b22", border="#30363d", text="#e6edf3",
                 key="#8b949e", dots="#30363d", art="#6e7681", accent="#3fb950"),
    "light": dict(bg="#ffffff", bar="#f6f8fa", border="#d1d9e0", text="#1f2328",
                  key="#59636e", dots="#d1d9e0", art="#818b98", accent="#1a7f37"),
}

# Server rack. `*` marks a blinking LED.
ART = r"""
┌────────────────────────────┐
│ [::]  ═════════════  * * * │
├────────────────────────────┤
│ [::]  ═════════════  * * * │
├────────────────────────────┤
│ [::]  ═════════════  * * * │
├────────────────────────────┤
│ ░░░░░░░░░░░░░░░░░░░░░░░░░░ │
│ ░░░░░░░░░░░░░░░░░░░░░░░░░░ │
├────────────────────────────┤
│ [::]  ═════════════  * * * │
├────────────────────────────┤
│ >_ thibaut@nexpublica      │
└────────────────────────────┘
   ╨                      ╨
""".strip("\n").splitlines()

FONT = 14
LINE = 20
CHAR = 8.43  # monospace advance at 14px
WIDTH = 58   # info column width in characters


def api(url, data=None):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": USER}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def graphql(query, **variables):
    body = json.dumps({"query": query, "variables": variables}).encode()
    return api("https://api.github.com/graphql", body)["data"]


def stats():
    user = api(f"https://api.github.com/users/{USER}")
    repos = api(f"https://api.github.com/users/{USER}/repos?per_page=100&type=owner")
    created = datetime.fromisoformat(user["created_at"].replace("Z", "+00:00"))
    s = {
        "created": created,
        "repos": user["public_repos"],
        "stars": sum(r["stargazers_count"] for r in repos if not r["fork"]),
        "followers": user["followers"],
    }
    if TOKEN:
        q = """query($login:String!,$from:DateTime!,$to:DateTime!){user(login:$login){
          contributionsCollection(from:$from,to:$to){totalCommitContributions restrictedContributionsCount}}}"""
        commits, year = 0, created.year
        now = datetime.now(timezone.utc)
        while year <= now.year:
            start = max(created, datetime(year, 1, 1, tzinfo=timezone.utc))
            end = min(now, datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc))
            c = graphql(q, login=USER, **{"from": start.isoformat(), "to": end.isoformat()})
            c = c["user"]["contributionsCollection"]
            commits += c["totalCommitContributions"] + c["restrictedContributionsCount"]
            year += 1
        s["commits"] = commits
    else:
        s["commits"] = api(f"https://api.github.com/search/commits?q=author:{USER}")["total_count"]
    return s


def uptime(since):
    now = datetime.now(timezone.utc)
    months = (now.year - since.year) * 12 + now.month - since.month - (now.day < since.day)
    y, m = divmod(months, 12)
    anchor_month = since.month - 1 + months
    anchor = since.replace(year=since.year + anchor_month // 12, month=anchor_month % 12 + 1, day=min(since.day, 28))
    days = (now - anchor).days
    return f"{y} years, {m} months, {days} days"


def info_lines(s):
    head = "thibaut@nexpublica"
    rows = [
        ("title", head),
        ("rule", None),
        ("kv", "OS", "Arch Linux · Omarchy · Hyprland"),
        ("kv", "Host", "Nexpublica · Montpellier, FR"),
        ("kv", "Kernel", "Systems & Integration Engineer"),
        ("kv", "Uptime", uptime(s["created"])),
        ("kv", "Shell", "bash · PowerShell"),
        ("blank",),
        ("kv", "Virt", "Proxmox · VMware ESXi · Hyper-V"),
        ("kv", "Containers", "Docker · Kubernetes · OpenShift"),
        ("kv", "IaC", "Ansible · Terraform · Vagrant"),
        ("kv", "Langs", "Python · Go · Rust · Bash · TS"),
        ("kv", "Monitoring", "Grafana · Prometheus · Zabbix"),
        ("kv", "Motto", "automate everything possible"),
        ("blank",),
        ("section", "GitHub"),
        ("kv2", ("Repos", str(s["repos"])), ("Stars", str(s["stars"]))),
        ("kv2", ("Commits", f"{s['commits']:,}".replace(",", " ")),
         ("Followers", str(s["followers"]))),
        ("blank",),
        ("palette",),
    ]
    return rows


def kv(key, value, width, t):
    dots = width - len(key) - len(value) - 3
    return (f'<tspan fill="{t["key"]}">{escape(key)}</tspan>'
            f'<tspan fill="{t["text"]}">:</tspan>'
            f'<tspan fill="{t["dots"]}"> {"." * max(dots, 1)} </tspan>'
            f'<tspan fill="{t["text"]}">{escape(value)}</tspan>')


def render(s, t):
    rows = info_lines(s)
    pad, bar = 28, 38
    art_w = max(len(l) for l in ART) * CHAR
    info_x = pad + art_w + 36
    width = round(info_x + WIDTH * CHAR + pad)
    body_lines = 2 + len(rows)  # prompt + gap + rows
    height = bar + pad + body_lines * LINE + pad + 8

    out = []
    y0 = bar + pad + LINE  # first baseline (prompt)

    # prompt with typing effect
    cmd = "fastfetch"
    prompt = f"~ ❯ {cmd}"
    out.append(
        f'<text x="{pad}" y="{y0}"><tspan fill="{t["accent"]}">~ ❯ </tspan>'
        f'<tspan fill="{t["text"]}" class="type">{cmd}</tspan></text>')
    out.append(f'<rect class="caret" x="{pad + len(prompt) * CHAR + 2}" y="{y0 - FONT + 2}" '
               f'width="{CHAR}" height="{FONT + 2}" fill="{t["text"]}"/>')

    # art
    top = y0 + 2 * LINE
    led = 0
    for i, line in enumerate(ART):
        parts = []
        for ch in line:
            if ch == "*":
                parts.append(f'<tspan class="led l{led % 5}" fill="{t["accent"]}">●</tspan>')
                led += 1
            else:
                parts.append(escape(ch))
        out.append(f'<text class="in" style="animation-delay:{0.9 + i * 0.04:.2f}s" '
                   f'x="{pad}" y="{top + i * LINE}" fill="{t["art"]}">{"".join(parts)}</text>')

    # info
    for i, row in enumerate(rows):
        y = top + i * LINE
        delay = f"{1.0 + i * 0.06:.2f}s"
        kind = row[0]
        if kind == "blank":
            continue
        if kind == "title":
            user, host = row[1].split("@")
            content = (f'<tspan fill="{t["accent"]}" font-weight="700">{user}</tspan>'
                       f'<tspan fill="{t["text"]}">@</tspan>'
                       f'<tspan fill="{t["accent"]}" font-weight="700">{host}</tspan>')
        elif kind == "rule":
            content = f'<tspan fill="{t["dots"]}">{"─" * WIDTH}</tspan>'
        elif kind == "section":
            label = f"─ {row[1]} "
            content = (f'<tspan fill="{t["text"]}" font-weight="700">{escape(label)}</tspan>'
                       f'<tspan fill="{t["dots"]}">{"─" * (WIDTH - len(label))}</tspan>')
        elif kind == "kv":
            content = kv(row[1], row[2], WIDTH, t)
        elif kind == "kv2":
            half = (WIDTH - 3) // 2
            content = (kv(*row[1], half, t) + f'<tspan fill="{t["dots"]}"> │ </tspan>'
                       + kv(*row[2], WIDTH - 3 - half, t))
        elif kind == "palette":
            shades = ["#2d333b", "#444c56", "#636e7b", "#768390", "#adbac7", "#cdd9e5",
                      t["accent"], "#f0f6fc"]
            for j, c in enumerate(shades):
                out.append(f'<rect class="in" style="animation-delay:{delay}" x="{info_x + j * 3 * CHAR:.1f}" '
                           f'y="{y - FONT + 1}" width="{3 * CHAR:.1f}" height="{FONT + 3}" fill="{c}"/>')
            continue
        out.append(f'<text class="in" style="animation-delay:{delay}" x="{info_x:.1f}" y="{y}">{content}</text>')

    dots = "".join(f'<circle cx="{pad + i * 20}" cy="{bar / 2}" r="6" fill="{c}"/>'
                   for i, c in enumerate(["#ff5f57", "#febc2e", "#28c840"]))
    leds = "".join(f".l{i}{{animation-delay:{i * 0.37:.2f}s}}" for i in range(5))
    type_w = len(cmd) * CHAR

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" font-family="'JetBrains Mono','Fira Code',ui-monospace,SFMono-Regular,Menlo,Consolas,'Liberation Mono',monospace" font-size="{FONT}">
<style>
text{{white-space:pre}}
.in{{opacity:0;animation:in .35s ease-out forwards}}
@keyframes in{{from{{opacity:0;transform:translateX(-6px)}}to{{opacity:1;transform:none}}}}
.type{{clip-path:inset(0 100% 0 0);animation:type .6s steps({len(cmd)}) .2s forwards}}
@keyframes type{{to{{clip-path:inset(0 0 0 0)}}}}
.caret{{transform:translateX(-{type_w:.1f}px);animation:caret .6s steps({len(cmd)}) .2s forwards,blink 1s step-end 1s infinite}}
@keyframes caret{{to{{transform:none}}}}
@keyframes blink{{50%{{opacity:0}}}}
.led{{animation:led 2.2s step-end infinite}}
@keyframes led{{0%,100%{{opacity:1}}40%{{opacity:.25}}55%{{opacity:1}}70%{{opacity:.4}}}}
{leds}
@media (prefers-reduced-motion:reduce){{*{{animation:none!important;opacity:1!important;clip-path:none!important;transform:none!important}}}}
</style>
<rect x=".5" y=".5" width="{width - 1}" height="{height - 1}" rx="10" fill="{t["bg"]}" stroke="{t["border"]}"/>
<path d="M.5 {bar} V10.5 A10 10 0 0 1 10.5 .5 H{width - 10.5} A10 10 0 0 1 {width - .5} 10.5 V{bar} Z" fill="{t["bar"]}"/>
<line x1="0" y1="{bar}" x2="{width}" y2="{bar}" stroke="{t["border"]}"/>
{dots}
<text x="{width / 2}" y="{bar / 2 + 4}" text-anchor="middle" fill="{t["key"]}" font-size="12">thibaut@nexpublica: ~</text>
{chr(10).join(out)}
</svg>
"""


def main():
    s = stats()
    OUT.mkdir(exist_ok=True)
    for name, theme in THEMES.items():
        (OUT / f"card-{name}.svg").write_text(render(s, theme), encoding="utf-8")
    print(f"ok: {s['repos']} repos, {s['stars']} stars, {s['commits']} commits, {s['followers']} followers")


if __name__ == "__main__":
    main()
