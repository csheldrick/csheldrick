#!/usr/bin/env python3
"""Generate a self-contained SVG profile panel from GitHub API data.

The panel intentionally uses public GitHub data only. A broader token can be
supplied via GH_TOKEN, but repository names from private data are never queried
or rendered by this script.
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
GRAPHQL = "https://api.github.com/graphql"
USER = os.environ.get("PROFILE_USER", "csheldrick")
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
OUTPUT = Path(os.environ.get("PROFILE_OUTPUT", "assets/github-signal.svg"))

HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": f"{USER}-profile-signal",
    "X-GitHub-Api-Version": "2022-11-28",
}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"


def request_json(url: str, *, data: dict | None = None) -> dict | list:
    body = None
    headers = dict(HEADERS)
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers)
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
    results: list = []
    for page in range(1, pages + 1):
        params["page"] = page
        batch = api(path, params)
        if not isinstance(batch, list):
            break
        results.extend(batch)
        if len(batch) < 100:
            break
    return results


def search_total(query: str) -> int:
    result = api("/search/issues", {"q": query, "per_page": 1})
    if isinstance(result, dict):
        return int(result.get("total_count", 0))
    return 0


def graphql_contributions(start: dt.datetime, end: dt.datetime) -> tuple[dict[str, int], dict[str, int]] | None:
    if not TOKEN:
        return None
    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          totalCommitContributions
          totalIssueContributions
          totalPullRequestContributions
          totalPullRequestReviewContributions
          restrictedContributionsCount
          contributionCalendar {
            totalContributions
            weeks {
              contributionDays { date contributionCount }
            }
          }
        }
      }
    }
    """
    payload = {
        "query": query,
        "variables": {
            "login": USER,
            "from": start.isoformat().replace("+00:00", "Z"),
            "to": end.isoformat().replace("+00:00", "Z"),
        },
    }
    try:
        result = request_json(GRAPHQL, data=payload)
        if not isinstance(result, dict) or result.get("errors"):
            return None
        collection = result["data"]["user"]["contributionsCollection"]
        calendar = collection["contributionCalendar"]
        days: dict[str, int] = {}
        for week in calendar["weeks"]:
            for day in week["contributionDays"]:
                days[day["date"]] = int(day["contributionCount"])
        totals = {
            "total": int(calendar["totalContributions"]),
            "commits": int(collection["totalCommitContributions"]),
            "issues": int(collection["totalIssueContributions"]),
            "prs": int(collection["totalPullRequestContributions"]),
            "reviews": int(collection["totalPullRequestReviewContributions"]),
            "private": int(collection["restrictedContributionsCount"]),
        }
        return totals, days
    except (KeyError, TypeError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        return None


def public_activity_fallback(start: dt.datetime) -> tuple[dict[str, int], dict[str, int]]:
    # GitHub's public Events API is intentionally a short rolling window. This
    # fallback is labelled PUBLIC ACTIVITY in the generated panel so it is not
    # confused with GitHub's official contribution calendar.
    events = paged(f"/users/{USER}/events/public", pages=3)
    days: collections.Counter[str] = collections.Counter()
    for event in events:
        created = event.get("created_at", "")
        if not created:
            continue
        when = dt.datetime.fromisoformat(created.replace("Z", "+00:00"))
        if when >= start:
            days[when.date().isoformat()] += 1
    return {"total": sum(days.values()), "commits": 0, "issues": 0, "prs": 0, "reviews": 0, "private": 0}, dict(days)


def language_mix(repos: list[dict]) -> list[tuple[str, int]]:
    totals: collections.Counter[str] = collections.Counter()
    # Recent, owned, non-fork public repositories keep this representative and
    # bound the number of API calls.
    candidates = [r for r in repos if not r.get("fork") and not r.get("archived") and r.get("name") != USER][:10]
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


def level(count: int, peak: int) -> int:
    if count <= 0 or peak <= 0:
        return 0
    ratio = count / peak
    if ratio <= 0.15:
        return 1
    if ratio <= 0.35:
        return 2
    if ratio <= 0.65:
        return 3
    return 4


def render(stats: dict, contribution_days: dict[str, int], contribution_label: str, languages: list[tuple[str, int]], active: list[dict]) -> str:
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
    # Align 53 weeks to Sunday so the grid reads like GitHub's calendar.
    first = today - dt.timedelta(days=364)
    first -= dt.timedelta(days=(first.weekday() + 1) % 7)
    dates = [first + dt.timedelta(days=i) for i in range((today - first).days + 1)]
    peak = max((contribution_days.get(d.isoformat(), 0) for d in dates), default=0)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        '<title id="title">GitHub signal for ' + esc(USER) + '</title>',
        '<desc id="desc">A generated panel of GitHub contribution, pull request, repository and language statistics.</desc>',
        f'<rect width="100%" height="100%" rx="18" fill="{bg}"/>',
        f'<rect x="1" y="1" width="998" height="658" rx="18" fill="none" stroke="{border}" stroke-width="2"/>',
        '<style>text{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}.label{font-size:12px;letter-spacing:1.2px}.num{font-size:30px;font-weight:700}.small{font-size:13px}.repo{font-size:14px}</style>',
        f'<text x="38" y="50" fill="{green}" font-size="20" font-weight="700">&gt; github.signal --user {esc(USER)}</text>',
        f'<text x="38" y="76" fill="{muted}" class="small">generated from GitHub API · {now.strftime("%Y-%m-%d %H:%M UTC")} · public repository details only</text>',
    ]

    cards = [
        ("365D CONTRIBUTIONS" if contribution_label == "GITHUB CONTRIBUTIONS" else "PUBLIC ACTIVITY", compact(stats["contributions"])),
        ("MERGED PRS", compact(stats["merged_prs"])),
        ("EXTERNAL MERGES", compact(stats["external_merges"])),
        ("MERGED / 90D", compact(stats["merged_90d"])),
        ("PUBLIC REPOS", compact(stats["public_repos"])),
    ]
    card_x = 38
    card_y = 108
    card_w = 174
    gap = 16
    for i, (label_text, number) in enumerate(cards):
        x = card_x + i * (card_w + gap)
        parts.append(f'<rect x="{x}" y="{card_y}" width="{card_w}" height="94" rx="10" fill="{panel}" stroke="#1f2933"/>')
        parts.append(f'<text x="{x + 16}" y="{card_y + 28}" fill="{muted}" class="label">{esc(label_text)}</text>')
        parts.append(f'<text x="{x + 16}" y="{card_y + 67}" fill="{text}" class="num">{esc(number)}</text>')

    parts += [
        f'<text x="38" y="244" fill="{green}" font-size="14" font-weight="700">{esc(contribution_label)} · LAST YEAR</text>',
        f'<text x="38" y="266" fill="{muted}" class="small">activity density, not a productivity score</text>',
    ]

    grid_x, grid_y = 38, 286
    cell, cell_gap = 11, 3
    for d in dates:
        week = (d - first).days // 7
        dow = (d.weekday() + 1) % 7
        count = contribution_days.get(d.isoformat(), 0)
        color = heat[level(count, peak)]
        x = grid_x + week * (cell + cell_gap)
        y = grid_y + dow * (cell + cell_gap)
        parts.append(f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2" fill="{color}"><title>{d.isoformat()}: {count}</title></rect>')

    # Legend
    lx = 38
    ly = grid_y + 7 * (cell + cell_gap) + 22
    parts.append(f'<text x="{lx}" y="{ly}" fill="{muted}" class="small">less</text>')
    lx += 42
    for color in heat:
        parts.append(f'<rect x="{lx}" y="{ly - 11}" width="11" height="11" rx="2" fill="{color}"/>')
        lx += 15
    parts.append(f'<text x="{lx + 2}" y="{ly}" fill="{muted}" class="small">more</text>')

    # Language mix
    lang_x = 790
    parts.append(f'<text x="{lang_x}" y="244" fill="{green}" font-size="14" font-weight="700">PUBLIC CODE MIX</text>')
    parts.append(f'<text x="{lang_x}" y="266" fill="{muted}" class="small">recent owned repos</text>')
    total_lang = sum(v for _, v in languages) or 1
    bar_y = 295
    for name, amount in languages[:6]:
        pct = amount / total_lang
        parts.append(f'<text x="{lang_x}" y="{bar_y}" fill="{text}" class="small">{esc(name)}</text>')
        parts.append(f'<text x="960" y="{bar_y}" text-anchor="end" fill="{muted}" class="small">{pct * 100:4.1f}%</text>')
        parts.append(f'<rect x="{lang_x}" y="{bar_y + 8}" width="170" height="6" rx="3" fill="#161b22"/>')
        parts.append(f'<rect x="{lang_x}" y="{bar_y + 8}" width="{max(2, int(170 * pct))}" height="6" rx="3" fill="{green2}"/>')
        bar_y += 42

    # Footer activity list
    footer_y = 478
    parts += [
        f'<line x1="38" y1="{footer_y - 28}" x2="962" y2="{footer_y - 28}" stroke="#1f2933"/>',
        f'<text x="38" y="{footer_y}" fill="{green}" font-size="14" font-weight="700">RECENTLY ACTIVE PUBLIC REPOS</text>',
        f'<text x="650" y="{footer_y}" fill="{muted}" class="small">owned · non-fork · sorted by push</text>',
    ]
    row_y = footer_y + 32
    for idx, repo in enumerate(active[:4]):
        pushed = str(repo.get("pushed_at", ""))[:10]
        name = repo.get("name", "")
        stars = int(repo.get("stargazers_count", 0))
        fork_count = int(repo.get("forks_count", 0))
        parts.append(f'<text x="38" y="{row_y}" fill="{text}" class="repo">{idx + 1:02d}  {esc(name)}</text>')
        parts.append(f'<text x="540" y="{row_y}" fill="{muted}" class="small">pushed {esc(pushed)}</text>')
        parts.append(f'<text x="760" y="{row_y}" fill="{muted}" class="small">★ {stars}   forks {fork_count}</text>')
        row_y += 31

    parts += [
        f'<text x="38" y="628" fill="{muted}" class="small">stars across owned public repos: {stats["stars"]} · external merge = merged PR authored by {esc(USER)} outside repos owned by {esc(USER)}</text>',
        f'<circle cx="952" cy="623" r="5" fill="{green}"><animate attributeName="opacity" values="1;.25;1" dur="2s" repeatCount="indefinite"/></circle>',
        '</svg>',
    ]
    return "\n".join(parts) + "\n"


def main() -> int:
    now = dt.datetime.now(dt.timezone.utc)
    year_ago = now - dt.timedelta(days=365)
    ninety_ago = (now - dt.timedelta(days=90)).date().isoformat()

    profile = api(f"/users/{USER}")
    repos = paged(f"/users/{USER}/repos", {"type": "owner", "sort": "pushed"})
    if not isinstance(profile, dict):
        raise RuntimeError("GitHub profile response was not an object")

    owned = [r for r in repos if isinstance(r, dict) and r.get("owner", {}).get("login", "").lower() == USER.lower()]
    public_owned = [r for r in owned if not r.get("private")]
    public_original = [r for r in public_owned if not r.get("fork") and r.get("name") != USER]

    merged_prs = search_total(f"is:pr is:merged author:{USER}")
    try:
        external_merges = search_total(f"is:pr is:merged author:{USER} -user:{USER}")
    except urllib.error.HTTPError:
        external_merges = 0
    merged_90d = search_total(f"is:pr is:merged author:{USER} merged:>={ninety_ago}")

    contrib = graphql_contributions(year_ago, now)
    if contrib is None:
        totals, days = public_activity_fallback(year_ago)
        contribution_label = "PUBLIC ACTIVITY"
    else:
        totals, days = contrib
        contribution_label = "GITHUB CONTRIBUTIONS"

    stats = {
        "contributions": totals["total"],
        "merged_prs": merged_prs,
        "external_merges": external_merges,
        "merged_90d": merged_90d,
        "public_repos": len(public_original),
        "stars": sum(int(r.get("stargazers_count", 0)) for r in public_original),
    }
    languages = language_mix(public_original)
    active = sorted(public_original, key=lambda r: r.get("pushed_at") or "", reverse=True)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render(stats, days, contribution_label, languages, active), encoding="utf-8")
    print(f"wrote {OUTPUT}")
    print(json.dumps(stats, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, RuntimeError) as exc:
        print(f"profile stats generation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
