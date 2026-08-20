#!/usr/bin/env python3
"""Generate the GitHub profile signal from directly observable repository/PR data.

The signal deliberately does not use GitHub's profile contribution total. That
number follows GitHub-specific contribution eligibility and privacy rules and can
look very different from the repository activity visible to an authenticated
user. Instead, the activity trace is based on merged pull requests authored by
the configured user during the last 90 days.
"""

from __future__ import annotations

import collections
import datetime as dt
import html
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.github.com"
USER = os.environ.get("PROFILE_USER", "csheldrick")
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
PRIVATE_MODE = os.environ.get("PROFILE_PRIVATE", "").lower() in {"1", "true", "yes"}
OUTPUT = Path(os.environ.get("PROFILE_OUTPUT", "assets/github-signal.svg"))

HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": f"{USER}-profile-signal",
    "X-GitHub-Api-Version": "2022-11-28",
}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"


def request_json(url: str) -> dict | list:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def api(path: str, params: dict[str, str | int] | None = None) -> dict | list:
    url = f"{API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return request_json(url)


def paged(path: str, params: dict[str, str | int] | None = None, pages: int = 10) -> list:
    params = dict(params or {})
    params["per_page"] = 100
    out: list = []
    for page in range(1, pages + 1):
        params["page"] = page
        batch = api(path, params)
        if not isinstance(batch, list):
            break
        out.extend(batch)
        if len(batch) < 100:
            break
    return out


def search_total(query: str) -> int:
    result = api("/search/issues", {"q": query, "per_page": 1})
    return int(result.get("total_count", 0)) if isinstance(result, dict) else 0


def search_items(query: str, pages: int = 10) -> tuple[int, list[dict]]:
    out: list[dict] = []
    total = 0
    for page in range(1, pages + 1):
        result = api(
            "/search/issues",
            {
                "q": query,
                "per_page": 100,
                "page": page,
                "sort": "updated",
                "order": "desc",
            },
        )
        if not isinstance(result, dict):
            break
        total = int(result.get("total_count", 0))
        batch = [item for item in result.get("items", []) if isinstance(item, dict)]
        out.extend(batch)
        if len(batch) < 100 or len(out) >= min(total, 1000):
            break
    return total, out


def owned_repositories() -> list[dict]:
    if PRIVATE_MODE:
        try:
            repos = paged(
                "/user/repos",
                {"visibility": "all", "affiliation": "owner", "sort": "pushed"},
            )
            return [
                r
                for r in repos
                if isinstance(r, dict)
                and r.get("owner", {}).get("login", "").lower() == USER.lower()
            ]
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            pass

    repos = paged(f"/users/{USER}/repos", {"type": "owner", "sort": "pushed"})
    return [
        r
        for r in repos
        if isinstance(r, dict)
        and r.get("owner", {}).get("login", "").lower() == USER.lower()
    ]


def language_mix(repos: list[dict]) -> list[tuple[str, int]]:
    totals: collections.Counter[str] = collections.Counter()
    candidates = [
        r
        for r in repos
        if not r.get("fork") and not r.get("archived") and r.get("name") != USER
    ][:16]
    for repo in candidates:
        try:
            langs = api(f"/repos/{USER}/{repo['name']}/languages")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            continue
        if isinstance(langs, dict):
            for language, amount in langs.items():
                totals[language] += int(amount)
    return totals.most_common(6)


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def compact(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}m"
    if value >= 1_000:
        return f"{value / 1_000:.1f}k"
    return str(value)


def parse_day(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def merge_days(items: list[dict], start: dt.date, end: dt.date) -> dict[str, int]:
    days: collections.Counter[str] = collections.Counter()
    for item in items:
        # A merged PR closes at merge time. GitHub's issue-search representation
        # does not guarantee a top-level merged_at field, so closed_at is the
        # stable timestamp available on every merged PR search result.
        day = parse_day(item.get("closed_at"))
        if not day:
            continue
        parsed = dt.date.fromisoformat(day)
        if start <= parsed <= end:
            days[day] += 1
    return dict(days)


def intensity(count: int, peak: int) -> int:
    if count <= 0 or peak <= 0:
        return 0
    ratio = count / peak
    if ratio <= 0.20:
        return 1
    if ratio <= 0.45:
        return 2
    if ratio <= 0.70:
        return 3
    return 4


def render(
    stats: dict,
    days: dict[str, int],
    languages: list[tuple[str, int]],
    active_repos: list[dict],
) -> str:
    width, height = 1000, 660
    bg = "#0d1117"
    panel = "#0b1510"
    border = "#1f6f3f"
    text = "#c9d1d9"
    muted = "#7d8590"
    green = "#39d353"
    green2 = "#26a641"
    heat = ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"]

    now = dt.datetime.now(dt.timezone.utc)
    today = now.date()
    start = today - dt.timedelta(days=89)
    peak = max(days.values(), default=0)

    visibility = (
        "private + public activity · repository names shown"
        if stats["private_mode"]
        else "public-only mode · add PROFILE_STATS_TOKEN for private activity"
    )

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        '<title id="title">GitHub signal for ' + esc(USER) + '</title>',
        '<desc id="desc">Generated pull request, repository and language activity statistics.</desc>',
        f'<rect width="100%" height="100%" rx="18" fill="{bg}"/>',
        f'<rect x="1" y="1" width="998" height="658" rx="18" fill="none" stroke="{border}" stroke-width="2"/>',
        '<style>text{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}.label{font-size:12px;letter-spacing:1.1px}.num{font-size:30px;font-weight:700}.small{font-size:13px}.repo{font-size:14px}</style>',
        f'<text x="38" y="50" fill="{green}" font-size="20" font-weight="700">&gt; github.signal --user {esc(USER)}</text>',
        f'<text x="38" y="76" fill="{muted}" class="small">generated {now.strftime("%Y-%m-%d %H:%M UTC")} · {esc(visibility)}</text>',
    ]

    cards = [
        ("MERGED / 90D", compact(stats["merged_90d"])),
        ("MERGED PRS", compact(stats["merged_total"])),
        ("ACTIVE DAYS / 90D", compact(stats["active_days_90d"])),
        ("EXTERNAL MERGES", compact(stats["external_merges"])),
        (
            "PRIVATE REPOS" if stats["private_mode"] else "PUBLIC REPOS",
            compact(stats["private_repos"] if stats["private_mode"] else stats["public_repos"]),
        ),
    ]
    card_x, card_y, card_w, gap = 38, 108, 174, 16
    for i, (label, number) in enumerate(cards):
        x = card_x + i * (card_w + gap)
        parts.append(f'<rect x="{x}" y="{card_y}" width="{card_w}" height="94" rx="10" fill="{panel}" stroke="#1f2933"/>')
        parts.append(f'<text x="{x + 16}" y="{card_y + 28}" fill="{muted}" class="label">{esc(label)}</text>')
        parts.append(f'<text x="{x + 16}" y="{card_y + 67}" fill="{text}" class="num">{esc(number)}</text>')

    parts += [
        f'<text x="38" y="244" fill="{green}" font-size="14" font-weight="700">MERGE SIGNAL · LAST 90 DAYS</text>',
        f'<text x="38" y="266" fill="{muted}" class="small">each cell = merged PRs authored by {esc(USER)} on that day · private included when token allows</text>',
    ]

    # 13-week calendar, Sunday-first, enlarged so the shorter 90-day window is
    # visually useful instead of a mostly-empty year grid.
    first = start - dt.timedelta(days=(start.weekday() + 1) % 7)
    grid_x, grid_y, cell, cell_gap = 38, 286, 20, 5
    dates = [first + dt.timedelta(days=i) for i in range((today - first).days + 1)]
    for day in dates:
        week = (day - first).days // 7
        dow = (day.weekday() + 1) % 7
        count = days.get(day.isoformat(), 0) if day >= start else 0
        color = heat[intensity(count, peak)]
        x = grid_x + week * (cell + cell_gap)
        y = grid_y + dow * (cell + cell_gap)
        parts.append(
            f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="3" fill="{color}">'
            f'<title>{day.isoformat()}: {count} merged PRs</title></rect>'
        )

    ly = grid_y + 7 * (cell + cell_gap) + 18
    parts.append(f'<text x="38" y="{ly}" fill="{muted}" class="small">0</text>')
    lx = 58
    for color in heat:
        parts.append(f'<rect x="{lx}" y="{ly - 13}" width="13" height="13" rx="2" fill="{color}"/>')
        lx += 17
    parts.append(f'<text x="{lx + 2}" y="{ly}" fill="{muted}" class="small">peak {peak}/day</text>')

    lang_x = 485
    code_mix_label = "ALL CODE MIX" if stats["private_mode"] else "PUBLIC CODE MIX"
    parts.append(f'<text x="{lang_x}" y="244" fill="{green}" font-size="14" font-weight="700">{code_mix_label}</text>')
    parts.append(f'<text x="{lang_x}" y="266" fill="{muted}" class="small">recent owned repositories</text>')
    total_lang = sum(v for _, v in languages) or 1
    bar_y = 295
    for name, amount in languages[:6]:
        pct = amount / total_lang
        parts.append(f'<text x="{lang_x}" y="{bar_y}" fill="{text}" class="small">{esc(name)}</text>')
        parts.append(f'<text x="960" y="{bar_y}" text-anchor="end" fill="{muted}" class="small">{pct * 100:4.1f}%</text>')
        parts.append(f'<rect x="{lang_x}" y="{bar_y + 8}" width="475" height="6" rx="3" fill="#161b22"/>')
        parts.append(f'<rect x="{lang_x}" y="{bar_y + 8}" width="{max(2, int(475 * pct))}" height="6" rx="3" fill="{green2}"/>')
        bar_y += 42

    footer_y = 478
    parts += [
        f'<line x1="38" y1="{footer_y - 28}" x2="962" y2="{footer_y - 28}" stroke="#1f2933"/>',
        f'<text x="38" y="{footer_y}" fill="{green}" font-size="14" font-weight="700">RECENTLY ACTIVE REPOS</text>',
        f'<text x="650" y="{footer_y}" fill="{muted}" class="small">owned · non-fork · sorted by push</text>',
    ]
    row_y = footer_y + 32
    for idx, repo in enumerate(active_repos[:4]):
        pushed = str(repo.get("pushed_at", ""))[:10]
        name = repo.get("name", "")
        visibility = "private" if repo.get("private") else "public"
        stars = int(repo.get("stargazers_count", 0))
        parts.append(f'<text x="38" y="{row_y}" fill="{text}" class="repo">{idx + 1:02d}  {esc(name)}</text>')
        parts.append(f'<text x="520" y="{row_y}" fill="{muted}" class="small">{visibility} · pushed {esc(pushed)}</text>')
        parts.append(f'<text x="860" y="{row_y}" fill="{muted}" class="small">★ {stars}</text>')
        row_y += 31

    footer = (
        f'public repos: {stats["public_repos"]} · private repos: {stats["private_repos"]} · '
        f'90d merge trace: {stats["trace_items"]}/{stats["merged_90d"]} PRs loaded'
    )
    parts += [
        f'<text x="38" y="628" fill="{muted}" class="small">{esc(footer)}</text>',
        f'<circle cx="952" cy="623" r="5" fill="{green}"><animate attributeName="opacity" values="1;.25;1" dur="2s" repeatCount="indefinite"/></circle>',
        '</svg>',
    ]
    return "\n".join(parts) + "\n"


def main() -> int:
    now = dt.datetime.now(dt.timezone.utc)
    today = now.date()
    start_90d = today - dt.timedelta(days=89)

    profile = api(f"/users/{USER}")
    if not isinstance(profile, dict):
        raise RuntimeError("GitHub profile response was not an object")

    owned = owned_repositories()
    public_owned = [r for r in owned if not r.get("private")]
    private_owned = [r for r in owned if r.get("private")]
    originals = [
        r
        for r in owned
        if not r.get("fork") and not r.get("archived") and r.get("name") != USER
    ]
    public_originals = [r for r in originals if not r.get("private")]

    merged_total = search_total(f"is:pr is:merged author:{USER}")
    external_merges = search_total(f"is:pr is:merged author:{USER} -user:{USER}")
    merged_90d, merged_items = search_items(
        f"is:pr is:merged author:{USER} merged:>={start_90d.isoformat()}"
    )
    days = merge_days(merged_items, start_90d, today)

    private_mode = PRIVATE_MODE and bool(private_owned)
    stats = {
        "merged_90d": merged_90d,
        "merged_total": merged_total,
        "active_days_90d": sum(1 for value in days.values() if value > 0),
        "external_merges": external_merges,
        "public_repos": len(public_originals),
        "private_repos": len(private_owned) if private_mode else 0,
        "private_mode": private_mode,
        "trace_items": len(merged_items),
    }

    signal_repos = originals if private_mode else public_originals
    languages = language_mix(signal_repos)
    active_repos = sorted(signal_repos, key=lambda r: r.get("pushed_at") or "", reverse=True)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render(stats, days, languages, active_repos), encoding="utf-8")
    print(f"wrote {OUTPUT}")
    print(json.dumps(stats, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, RuntimeError) as exc:
        print(f"profile signal generation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
