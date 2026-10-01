#!/usr/bin/env python3
"""Generate the terminal-style profile panes (dark + light SVG).

  assets/card-*.svg      ~ ❯ fastfetch
  assets/docker-*.svg    ~ ❯ docker ps
  assets/trophies-*.svg  ~ ❯ achievements --shelf
  assets/contrib-*.svg   ~ ❯ git log --3d   +   systemctl status profile.timer

Stdlib only. Uses GITHUB_TOKEN (GraphQL) when available, falls back to the
public REST API otherwise.
"""
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape

USER = "Foufou-exe"
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets"
CONTRIB = ROOT / "profile-3d-contrib"
ACH_CACHE = OUT / "achievements.json"
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
NOW = datetime.now(timezone.utc)

THEMES = {
    "dark": dict(bg="#0d1117", bar="#161b22", border="#30363d", text="#e6edf3",
                 key="#8b949e", dots="#30363d", art="#6e7681", accent="#3fb950",
                 shelf="#21262d", contrib="profile-night-green.svg"),
    "light": dict(bg="#ffffff", bar="#f6f8fa", border="#d1d9e0", text="#1f2328",
                  key="#59636e", dots="#d1d9e0", art="#818b98", accent="#1a7f37",
                  shelf="#eaeef2", contrib="profile-green-animate.svg"),
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

# slug, display name, how to unlock (shown while locked)
ACHIEVEMENTS = [
    ("pull-shark", "Pull Shark", "get 2 PRs merged"),
    ("quickdraw", "Quickdraw", "close issue < 5min"),
    ("yolo", "YOLO", "merge without review"),
    ("pair-extraordinaire", "Pair Extraordinaire", "coauthor a merged PR"),
    ("starstruck", "Starstruck", "16 stars on a repo"),
    ("galaxy-brain", "Galaxy Brain", "2 accepted answers"),
    ("public-sponsor", "Public Sponsor", "sponsor a dev"),
    ("heart-on-your-sleeve", "Heart On Your Sleeve", "react with a heart"),
    ("open-sourcerer", "Open Sourcerer", "PRs in many repos"),
    ("arctic-code-vault-contributor", "Arctic Code Vault", "retired in 2020"),
]
# primary language -> the image you'd actually `docker run`
IMAGES = {"python": "python:3.12", "rust": "rust:1-slim", "go": "golang:1.23", "typescript": "node:lts",
          "javascript": "node:lts", "vue": "node:lts", "dart": "dart:stable", "c++": "gcc:14", "c": "gcc:14",
          "c#": "dotnet/sdk:8", "java": "temurin:21", "php": "php:8-fpm", "shell": "alpine:3",
          "powershell": "pwsh:lts", "html": "nginx:alpine", "css": "nginx:alpine"}
TIER_COLORS = {2: "#f9bfa7", 3: "#d3d3d3", 4: "#eac54f"}  # bronze, silver, gold

FONT = 14
LINE = 20
CHAR = 8.43  # monospace advance at 14px
WIDTH = 58   # info column width in characters
PAD, BAR = 28, 38
W = 834      # every pane shares the same width


# ── data ──────────────────────────────────────────────────────────────────────

def fetch(url, data=None, accept="application/vnd.github+json", raw=False):
    headers = {"Accept": accept, "User-Agent": USER}
    if TOKEN and "api.github.com" in url:
        headers["Authorization"] = f"Bearer {TOKEN}"
    if "github.com/users/" in url:
        headers["X-Requested-With"] = "XMLHttpRequest"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read()
    return body if raw else json.loads(body)


def graphql(query, **variables):
    body = json.dumps({"query": query, "variables": variables}).encode()
    return fetch("https://api.github.com/graphql", body)["data"]


def stats():
    user = fetch(f"https://api.github.com/users/{USER}")
    repos = fetch(f"https://api.github.com/users/{USER}/repos?per_page=100&type=owner")
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
        commits = 0
        for year in range(created.year, NOW.year + 1):
            start = max(created, datetime(year, 1, 1, tzinfo=timezone.utc))
            end = min(NOW, datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc))
            c = graphql(q, login=USER, **{"from": start.isoformat(), "to": end.isoformat()})
            c = c["user"]["contributionsCollection"]
            commits += c["totalCommitContributions"] + c["restrictedContributionsCount"]
        s["commits"] = commits
    else:
        s["commits"] = fetch(f"https://api.github.com/search/commits?q=author:{USER}")["total_count"]
    return s


ICON_PX = 128  # 2x the displayed size, stays sharp on retina


def shrink(png):
    """Downscale a PNG to ICON_PX with Pillow or ImageMagick; keep it as is otherwise."""
    try:
        from io import BytesIO
        from PIL import Image
        im = Image.open(BytesIO(png))
        im.thumbnail((ICON_PX, ICON_PX), Image.LANCZOS)
        buf = BytesIO()
        im.save(buf, "PNG", optimize=True)
        return buf.getvalue()
    except ImportError:
        pass
    magick = shutil.which("magick") or shutil.which("convert")
    if magick:
        r = subprocess.run([magick, "png:-", "-resize", f"{ICON_PX}x{ICON_PX}", "-strip", "png:-"],
                           input=png, capture_output=True)
        if r.returncode == 0 and r.stdout:
            return r.stdout
    return png


def projects():
    """Pinned repos (GraphQL, needs a token) or the most recently pushed ones."""
    if TOKEN:
        q = """query($login:String!){user(login:$login){pinnedItems(first:6,types:REPOSITORY){nodes{
          ... on Repository{name description stargazerCount forkCount pushedAt isArchived
          primaryLanguage{name}}}}}}"""
        nodes = graphql(q, login=USER)["user"]["pinnedItems"]["nodes"]
        if nodes:
            return "pinned", [{"name": n["name"], "desc": n["description"] or "",
                     "lang": (n["primaryLanguage"] or {}).get("name") or "scratch",
                     "stars": n["stargazerCount"], "forks": n["forkCount"],
                     "pushed": n["pushedAt"], "archived": n["isArchived"]} for n in nodes]
    repos = fetch(f"https://api.github.com/users/{USER}/repos?per_page=100&type=owner&sort=pushed")
    repos = [r for r in repos if not r["fork"] and r["name"] != USER][:6]
    return "recently pushed", [{"name": r["name"], "desc": r["description"] or "", "lang": r["language"] or "scratch",
             "stars": r["stargazers_count"], "forks": r["forks_count"],
             "pushed": r["pushed_at"], "archived": r["archived"]} for r in repos]


def ago(iso):
    """Docker-style duration: '3 days', 'About an hour', '2 months'."""
    secs = (NOW - datetime.fromisoformat(iso.replace("Z", "+00:00"))).total_seconds()
    for unit, size in (("year", 31536000), ("month", 2592000), ("week", 604800),
                       ("day", 86400), ("hour", 3600), ("minute", 60)):
        n = int(secs // size)
        if n >= 2:
            return f"{n} {unit}s"
        if n == 1:
            return "About an hour" if unit == "hour" else f"1 {unit}"
    return "Less than a second"


def achievements():
    """Scrape unlocked achievements from the profile hovercards (no public API)."""
    cache = json.loads(ACH_CACHE.read_text()) if ACH_CACHE.exists() else {}
    result = {}
    for slug, *_ in ACHIEVEMENTS:
        url = f"https://github.com/users/{USER}/achievements/{slug}/detail?hovercard=1"
        try:
            html = fetch(url, accept="text/html", raw=True).decode()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue  # locked
            if slug in cache:
                result[slug] = cache[slug]
            continue
        except urllib.error.URLError:
            if slug in cache:
                result[slug] = cache[slug]
            continue
        imgs = re.findall(r'src="(https://github\.githubassets\.com/assets/[^"]+\.png)"', html)
        rank = ["default", "bronze", "silver", "gold"]
        imgs = [i for i in imgs if "-detail-" not in i] or imgs
        img = max(imgs, key=lambda u: next((n for n, r in enumerate(rank) if f"-{r}-" in u), 0))
        tier = re.search(r">\s*x(\d)\s*<", html)
        date = re.search(r'datetime="([^"]+)"', html)
        cached = cache.get(slug, {})
        icon = cached.get("icon") if (cached.get("img"), cached.get("size")) == (img, ICON_PX) else None
        if not icon:
            icon = base64.b64encode(shrink(fetch(img, accept="image/png", raw=True))).decode()
        result[slug] = {"img": img, "size": ICON_PX, "icon": icon, "tier": int(tier.group(1)) if tier else 1,
                        "since": date.group(1)[:10] if date else ""}
    ACH_CACHE.write_text(json.dumps(result, indent=1))
    return result


def uptime(since):
    months = (NOW.year - since.year) * 12 + NOW.month - since.month - (NOW.day < since.day)
    y, m = divmod(months, 12)
    anchor_month = since.month - 1 + months
    anchor = since.replace(year=since.year + anchor_month // 12, month=anchor_month % 12 + 1,
                           day=min(since.day, 28))
    return f"{y} years, {m} months, {(NOW - anchor).days} days"


def fmt(n):
    return f"{n:,}".replace(",", " ")


# ── svg helpers ───────────────────────────────────────────────────────────────

CSS = """
text{white-space:pre}
.in{opacity:0;animation:in .35s ease-out forwards}
@keyframes in{from{opacity:0;transform:translateX(-6px)}to{opacity:1;transform:none}}
.pop{opacity:0;transform-box:fill-box;transform-origin:center;animation:pop .45s cubic-bezier(.3,1.6,.5,1) forwards}
@keyframes pop{from{opacity:0;transform:scale(.4)}to{opacity:1;transform:scale(1)}}
.float{transform-box:fill-box;animation:float 3.2s ease-in-out infinite}
@keyframes float{50%{transform:translateY(-4px)}}
.fill{transform-box:fill-box;transform:scaleX(0);animation:fill 1.2s ease-out forwards}
@keyframes fill{to{transform:scaleX(1)}}
.type{clip-path:inset(0 100% 0 0)}
@keyframes type{to{clip-path:inset(0 0 0 0)}}
@keyframes caret{to{transform:none}}
@keyframes blink{50%{opacity:0}}
@keyframes hide{to{opacity:0}}
.led{animation:led 2.2s step-end infinite}
@keyframes led{0%,100%{opacity:1}40%{opacity:.25}55%{opacity:1}70%{opacity:.4}}
.pulse{animation:pulse 1.6s ease-in-out infinite}
@keyframes pulse{50%{opacity:.35}}
@media (prefers-reduced-motion:reduce){*{animation:none!important;opacity:1!important;clip-path:none!important;transform:none!important}.tmp{display:none}}
"""


def d(sec):
    return f'style="animation-delay:{sec:.2f}s"'


def prompt(x, y, cmd, t, start, last=False):
    """`~ ❯ cmd` typed out from `start`; the caret only stays on the last prompt."""
    n, typ = len(cmd), len(cmd) * 0.065
    caret_x = x + (4 + n) * CHAR + 2
    caret_anim = (f"caret {typ:.2f}s steps({n}) {start:.2f}s forwards,"
                  + (f"blink 1s step-end {start + typ + .2:.2f}s infinite" if last
                     else f"hide .01s {start + typ + .25:.2f}s forwards"))
    return (f'<text x="{x}" y="{y}"><tspan fill="{t["accent"]}">~ ❯ </tspan>'
            f'<tspan fill="{t["text"]}" class="type" style="animation:type {typ:.2f}s steps({n}) {start:.2f}s forwards">'
            f'{escape(cmd)}</tspan></text>'
            f'<rect x="{caret_x:.1f}" y="{y - FONT + 2}" width="{CHAR}" height="{FONT + 2}" fill="{t["text"]}" '
            f'{"" if last else 'class="tmp" '}style="transform:translateX(-{n * CHAR:.1f}px);animation:{caret_anim}"/>')


def window(title, height, body, t):
    lights = "".join(f'<circle cx="{PAD + i * 20}" cy="{BAR / 2}" r="6" fill="{c}"/>'
                     for i, c in enumerate(["#ff5f57", "#febc2e", "#28c840"]))
    return f"""<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{W}" height="{height}" viewBox="0 0 {W} {height}" font-family="'JetBrains Mono','Fira Code',ui-monospace,SFMono-Regular,Menlo,Consolas,'Liberation Mono',monospace" font-size="{FONT}">
<style>{CSS}</style>
<rect x=".5" y=".5" width="{W - 1}" height="{height - 1}" rx="10" fill="{t["bg"]}" stroke="{t["border"]}"/>
<path d="M.5 {BAR} V10.5 A10 10 0 0 1 10.5 .5 H{W - 10.5} A10 10 0 0 1 {W - .5} 10.5 V{BAR} Z" fill="{t["bar"]}"/>
<line x1="0" y1="{BAR}" x2="{W}" y2="{BAR}" stroke="{t["border"]}"/>
{lights}
<text x="{W / 2}" y="{BAR / 2 + 4}" text-anchor="middle" fill="{t["key"]}" font-size="12">{escape(title)}</text>
{body}
</svg>
"""


def kv(key, value, width, t):
    dots = width - len(key) - len(value) - 3
    return (f'<tspan fill="{t["key"]}">{escape(key)}</tspan>'
            f'<tspan fill="{t["text"]}">:</tspan>'
            f'<tspan fill="{t["dots"]}"> {"." * max(dots, 1)} </tspan>'
            f'<tspan fill="{t["text"]}">{escape(value)}</tspan>')


# ── pane 1: fastfetch ─────────────────────────────────────────────────────────

def render_card(s, t):
    rows = [
        ("title", "thibaut@nexpublica"),
        ("rule",),
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
        ("kv2", ("Commits", fmt(s["commits"])), ("Followers", str(s["followers"]))),
        ("blank",),
        ("palette",),
    ]
    info_x = W - PAD - WIDTH * CHAR
    height = BAR + PAD + (2 + len(rows)) * LINE + PAD + 8
    y0 = BAR + PAD + LINE
    out = [prompt(PAD, y0, "fastfetch", t, .2, last=True)]

    top = y0 + 2 * LINE
    led = 0
    for i, line in enumerate(ART):
        parts = []
        for ch in line:
            if ch == "*":
                parts.append(f'<tspan class="led" style="animation-delay:{led % 5 * .37:.2f}s" fill="{t["accent"]}">●</tspan>')
                led += 1
            else:
                parts.append(escape(ch))
        out.append(f'<text class="in" {d(.9 + i * .04)} x="{PAD}" y="{top + i * LINE}" fill="{t["art"]}">{"".join(parts)}</text>')

    for i, row in enumerate(rows):
        y, delay, kind = top + i * LINE, 1.0 + i * .06, row[0]
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
            shades = ["#2d333b", "#444c56", "#636e7b", "#768390", "#adbac7", "#cdd9e5", t["accent"], "#f0f6fc"]
            out += [f'<rect class="in" {d(delay)} x="{info_x + j * 3 * CHAR:.1f}" y="{y - FONT + 1}" '
                    f'width="{3 * CHAR:.1f}" height="{FONT + 3}" fill="{c}"/>' for j, c in enumerate(shades)]
            continue
        out.append(f'<text class="in" {d(delay)} x="{info_x:.1f}" y="{y}">{content}</text>')

    return window("thibaut@nexpublica: ~", height, "\n".join(out), t)


# ── pane 2: docker ps ─────────────────────────────────────────────────────────

def render_docker(projects, t):
    source, repos = projects
    fs, cw = 12, 7.23  # smaller font so the table fits like a real 100+ col terminal
    cols = [("CONTAINER ID", 12), ("IMAGE", 13), ("COMMAND", 23), ("STATUS", 15), ("PORTS", 11), ("NAMES", 0)]
    gap = 2
    total = int((W - 2 * PAD) / cw)
    used = sum(w for _, w in cols) + gap * (len(cols) - 1)
    cols[-1] = ("NAMES", total - used)

    def cell(text, width):
        text = text if len(text) <= width else text[: width - 1] + "…"
        return escape(text.ljust(width + gap))

    y0 = BAR + PAD + LINE
    out = [prompt(PAD, y0, "docker ps", t, .2, last=True)]
    y = y0 + 2 * LINE
    head = "".join(cell(n, w) for n, w in cols)
    out.append(f'<text class="in" {d(.9)} x="{PAD}" y="{y}" font-size="{fs}" fill="{t["key"]}">{head}</text>')
    for i, r in enumerate(repos):
        y += LINE + 4
        cid = hashlib.sha1(r["name"].encode()).hexdigest()[:12]
        image = IMAGES.get(r["lang"].lower(), f'{r["lang"].lower().replace(" ", "-")}:latest')
        cmd = f'"{r["desc"].strip() or r["name"]}"'
        status = f'Exited (0) {ago(r["pushed"])} ago' if r["archived"] else f'Up {ago(r["pushed"])}'
        ports = f'{r["stars"]}★->{r["forks"]}/fork'
        parts = [(cid, t["art"]), (image, t["text"]), (cmd, t["key"]),
                 (status, t["key"] if r["archived"] else t["accent"]), (ports, t["text"]), (r["name"], t["text"])]
        line = "".join(f'<tspan fill="{c}"{" font-weight=\"700\"" if k == 5 else ""}>{cell(v, cols[k][1])}</tspan>'
                       for k, (v, c) in enumerate(parts))
        out.append(f'<text class="in" {d(1.0 + i * .12)} x="{PAD}" y="{y}" font-size="{fs}">{line}</text>')

    up = sum(not r["archived"] for r in repos)
    y += 2 * LINE
    out.append(f'<text class="in" {d(1.2 + len(repos) * .12)} x="{PAD}" y="{y}" font-size="{fs}">'
               f'<tspan fill="{t["accent"]}">●</tspan><tspan fill="{t["key"]}"> {up} running · '
               f'{len(repos) - up} exited · built from {source} repositories</tspan></text>')
    height = round(y + PAD + 4)
    return window("thibaut@nexpublica: ~/projects", height, "\n".join(out), t)


# ── pane 3: trophy shelf ──────────────────────────────────────────────────────

def render_trophies(ach, t):
    cols, icon = 5, 64
    cell_w = (W - 2 * PAD) / cols
    shelf_h = icon + 76
    items = sorted(ACHIEVEMENTS, key=lambda a: a[0] not in ach)  # unlocked first
    rows = -(-len(items) // cols)

    y0 = BAR + PAD + LINE
    out = [prompt(PAD, y0, "achievements --shelf", t, .2, last=True)]

    # progress bar
    got, total = len(ach), len(ACHIEVEMENTS)
    y = y0 + 2 * LINE
    bar_x, bar_w = PAD + 16 * CHAR, 30 * CHAR
    out.append(f'<text class="in" {d(1.6)} x="{PAD}" y="{y}"><tspan fill="{t["key"]}">unlocked</tspan>'
               f'<tspan fill="{t["text"]}" font-weight="700">  {got}/{total}</tspan></text>')
    out.append(f'<rect class="in" {d(1.6)} x="{bar_x:.1f}" y="{y - 11}" width="{bar_w:.1f}" height="12" rx="3" fill="{t["shelf"]}"/>')
    out.append(f'<rect class="fill" {d(1.7)} x="{bar_x:.1f}" y="{y - 11}" width="{bar_w * got / total:.1f}" height="12" rx="3" fill="{t["accent"]}"/>')
    out.append(f'<text class="in" {d(2.6)} x="{bar_x + bar_w + 12:.1f}" y="{y}" fill="{t["key"]}">{round(100 * got / total)}%'
               f'<tspan fill="{t["dots"]}">  ·  next: </tspan><tspan fill="{t["text"]}">'
               f'{escape(next(a[1] for a in ACHIEVEMENTS if a[0] not in ach))}</tspan></text>')

    top = y + LINE + 10
    for i, (slug, name, hint) in enumerate(items):
        r, c = divmod(i, cols)
        cx = PAD + c * cell_w + cell_w / 2
        iy = top + r * shelf_h
        delay = 1.9 + i * .12
        a = ach.get(slug)
        g = [f'<g class="pop" {d(delay)}>']
        if a:
            g.append(f'<g class="float" style="animation-delay:{i * .4:.1f}s">'
                     f'<image x="{cx - icon / 2:.1f}" y="{iy}" width="{icon}" height="{icon}" '
                     f'href="data:image/png;base64,{a["icon"]}"/>')
            if a["tier"] > 1:
                chip = f'x{a["tier"]}'
                g.append(f'<rect x="{cx + 12:.1f}" y="{iy + icon - 16}" width="26" height="16" rx="8" '
                         f'fill="{TIER_COLORS.get(a["tier"], "#eac54f")}" stroke="{t["bg"]}" stroke-width="2"/>'
                         f'<text x="{cx + 25:.1f}" y="{iy + icon - 4}" text-anchor="middle" font-size="10" '
                         f'font-weight="700" fill="#1f2328">{chip}</text>')
            g.append('</g>')
            g.append(f'<text x="{cx:.1f}" y="{iy + icon + 22}" text-anchor="middle" font-size="12" '
                     f'font-weight="700" fill="{t["text"]}">{escape(name)}</text>')
            g.append(f'<text x="{cx:.1f}" y="{iy + icon + 38}" text-anchor="middle" font-size="11" '
                     f'fill="{t["key"]}">since {a["since"][:7]}</text>')
        else:
            g.append(f'<circle cx="{cx:.1f}" cy="{iy + icon / 2}" r="{icon / 2 - 4}" fill="none" '
                     f'stroke="{t["dots"]}" stroke-width="2" stroke-dasharray="4 5"/>'
                     f'<text x="{cx:.1f}" y="{iy + icon / 2 + 7}" text-anchor="middle" font-size="20" '
                     f'fill="{t["art"]}">?</text>')
            g.append(f'<text x="{cx:.1f}" y="{iy + icon + 22}" text-anchor="middle" font-size="12" '
                     f'fill="{t["art"]}">{escape(name)}</text>')
            g.append(f'<text x="{cx:.1f}" y="{iy + icon + 38}" text-anchor="middle" font-size="10" '
                     f'fill="{t["key"]}" opacity=".6">{escape(hint)}</text>')
        g.append('</g>')
        out.append("".join(g))

    # wooden-less shelves: a plank + brackets under each row
    for r in range(rows):
        py = top + r * shelf_h + icon + 50
        out.append(f'<g class="in" {d(1.8 + r * .1)}>'
                   f'<rect x="{PAD - 6}" y="{py}" width="{W - 2 * PAD + 12}" height="5" rx="2" fill="{t["shelf"]}"/>'
                   f'<rect x="{PAD + 20}" y="{py + 5}" width="4" height="10" fill="{t["shelf"]}"/>'
                   f'<rect x="{W - PAD - 24}" y="{py + 5}" width="4" height="10" fill="{t["shelf"]}"/></g>')

    height = round(top + rows * shelf_h + PAD - 6)
    return window("thibaut@nexpublica: ~/achievements", height, "\n".join(out), t)


# ── pane 4: 3D contributions + the workflow as a systemd timer ────────────────

def next_run():
    run = NOW.replace(hour=5, minute=0, second=0, microsecond=0)
    return run if run > NOW else run + timedelta(days=1)


def loop_3d(svg, period=7.0, wave=2.4):
    """The 3D graph grows once (SMIL, 3s). Make it loop like a gif: grow, hold, sink,
    with a phase offset per column so a wave sweeps across the calendar."""
    x = 0.0

    def sub(m):
        nonlocal x
        if m.group("x"):
            x = float(m.group("x"))
            return m.group(0)
        a, b = m.group("a"), m.group("b")
        tag = m.group("tag")
        return (f'<{tag} attributeName="{m.group("attr")}"{m.group("type") or ""} values="{a};{b};{b};{a}" '
                f'keyTimes="0;.3;.75;1" calcMode="spline" keySplines=".4 0 .2 1;0 0 1 1;.4 0 .2 1" '
                f'dur="{period}s" begin="{-wave * (1 - x / 1280):.2f}s" repeatCount="indefinite"{m.group("end")}')

    return re.sub(r'<g transform="translate\((?P<x>-?[\d.]+)[ ,]'
                  r'|<(?P<tag>animate(?:Transform)?) attributeName="(?P<attr>[^"]+)"(?P<type> type="[^"]+")?'
                  r' values="(?P<a>[^";]+);(?P<b>[^"]+)" dur="3s" repeatCount="1"(?P<end>\s*/?>)', sub, svg)


def render_contrib(s, ach, t):
    y0 = BAR + PAD + LINE
    out = [prompt(PAD, y0, "git log --graph --3d", t, .2)]
    y = y0 + LINE
    graph = CONTRIB / t["contrib"]
    if graph.exists():
        gw = W - 2 * PAD
        gh = gw * 850 / 1280
        b64 = base64.b64encode(loop_3d(graph.read_text()).encode()).decode()
        out.append(f'<clipPath id="g"><rect x="{PAD}" y="{y}" width="{gw}" height="{gh:.0f}" rx="8"/></clipPath>'
                   f'<g class="in" {d(1.4)}><image clip-path="url(#g)" x="{PAD}" y="{y}" width="{gw}" height="{gh:.0f}" '
                   f'href="data:image/svg+xml;base64,{b64}"/>'
                   f'<rect x="{PAD + .5}" y="{y + .5}" width="{gw - 1}" height="{gh - 1:.0f}" rx="8" fill="none" stroke="{t["border"]}"/></g>')
        y += gh + 2 * LINE
    else:
        y += 2 * LINE

    start = 2.0
    out.append(prompt(PAD, y, "systemctl status profile.timer", t, start, last=True))
    after = start + 30 * .065 + .4
    run = os.environ.get("GITHUB_RUN_NUMBER")
    stamp = NOW.strftime("%b %d %H:%M:%S")
    nxt = next_run().strftime("%a %Y-%m-%d %H:%M:%S UTC")
    pid = os.environ.get("GITHUB_RUN_ID", "1")[-4:]

    def label(k):
        return f'<tspan fill="{t["key"]}">{k:>11}: </tspan>'

    lines = [
        f'<tspan class="pulse" fill="{t["accent"]}">●</tspan><tspan fill="{t["text"]}" font-weight="700"> profile.timer</tspan>'
        f'<tspan fill="{t["key"]}"> - rebuild this README every morning</tspan>',
        label("Loaded") + f'<tspan fill="{t["text"]}">loaded (.github/workflows/profile.yml; </tspan>'
        f'<tspan fill="{t["accent"]}">enabled</tspan><tspan fill="{t["text"]}">)</tspan>',
        label("Active") + f'<tspan fill="{t["accent"]}" font-weight="700">active (waiting)</tspan>'
        f'<tspan fill="{t["text"]}"> since {NOW.strftime("%a %Y-%m-%d %H:%M UTC")}</tspan>',
        label("Trigger") + f'<tspan fill="{t["text"]}">{nxt}</tspan>',
        label("Triggers") + f'<tspan fill="{t["accent"]}">● </tspan><tspan fill="{t["text"]}">'
        f'profile.service{f" (run #{run})" if run else ""}</tspan>',
        "",
    ]
    journal = [
        f"fetched {s['repos']} repos · {fmt(s['commits'])} commits · {s['followers']} followers",
        f"unlocked {len(ach)}/{len(ACHIEVEMENTS)} achievements",
        "rendered 3D contribution graph",
        "rendered fastfetch · docker · shelf · timer panes",
        "Finished profile.service.",
    ]
    for j, msg in enumerate(journal):
        lines.append(f'<tspan fill="{t["art"]}">{stamp} runner profile[{pid}]: </tspan>'
                     f'<tspan fill="{t["accent"] if j == len(journal) - 1 else t["text"]}">{escape(msg)}</tspan>')

    y += LINE
    for i, content in enumerate(lines):
        if content:
            out.append(f'<text class="in" {d(after + i * .08)} x="{PAD}" y="{y + i * LINE}" font-size="13">{content}</text>')
    height = round(y + len(lines) * LINE + PAD - 6)
    return window("thibaut@nexpublica: ~/profile", height, "\n".join(out), t)


def main():
    s = stats()
    ach = achievements()
    repos = projects()
    OUT.mkdir(exist_ok=True)
    for name, theme in THEMES.items():
        (OUT / f"card-{name}.svg").write_text(render_card(s, theme), encoding="utf-8")
        (OUT / f"docker-{name}.svg").write_text(render_docker(repos, theme), encoding="utf-8")
        (OUT / f"trophies-{name}.svg").write_text(render_trophies(ach, theme), encoding="utf-8")
        (OUT / f"contrib-{name}.svg").write_text(render_contrib(s, ach, theme), encoding="utf-8")
    # summary read by check_profile.py (no secrets, no timestamps → no daily churn)
    (OUT / "stats.json").write_text(json.dumps({
        "repos": s["repos"], "stars": s["stars"], "commits": s["commits"], "followers": s["followers"],
        "achievements": sorted(ach), "projects": [r["name"] for r in repos[1]],
        "graph_3d": all((CONTRIB / t["contrib"]).exists() for t in THEMES.values()),
    }, indent=1) + "\n")
    print(f"ok: {s['repos']} repos, {s['stars']} stars, {s['commits']} commits, "
          f"{s['followers']} followers, achievements: {', '.join(f'{k} x{v['tier']}' for k, v in ach.items())}")


if __name__ == "__main__":
    main()
