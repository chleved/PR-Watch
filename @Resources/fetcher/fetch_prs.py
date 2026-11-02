#!/usr/bin/env python3
"""Fetch the status of a list of GitHub pull requests with the gh CLI.

Reads prs.txt (one PR per line) and writes into the data folder:
  prs.json  full state, also used as the cache between runs
  prs.inc   Rainmeter [Variables] file for the skin
  icons/    one avatar PNG per repo owner (refreshed weekly)

Usage: python fetch_prs.py [--list prs.txt] [--out-dir data] [--full] [--pad 20]

Needs the gh CLI on PATH and logged in (gh auth login). Set PR_WIDGET_GH to
point at a specific gh executable.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
GH = os.environ.get("PR_WIDGET_GH", "gh")
GH_TIMEOUT = 90
INCLUDE_PRERELEASES = False  # drafts are never counted
TERMINAL = {"MERGED", "CLOSED"}
ORDER = ["ERROR", "CONFLICT", "CI-FAIL", "CHANGES", "CI-RUNNING",
         "WAITING", "APPROVED", "DRAFT", "MERGED", "CLOSED"]
RANK = {s: i for i, s in enumerate(ORDER)}
PAD_ROWS = 20  # prs.inc always defines at least this many rows; the skin may show up to this many
MAX_REF = 28   # longest repo name shown (the PR chip sits right after it)
ICON_MAX_AGE = 7 * 24 * 3600  # re-download avatars after a week
ICON_TIMEOUT = 15
REPO_RE = re.compile(r"^[\w.-]+/[\w.-]+$")
# Accent colour per status (r,g,b) used by the skin for the row accent and the status chip.
THEME = {
    "ERROR": "255,107,107",
    "CONFLICT": "255,138,101",
    "CI-FAIL": "255,180,171",
    "CHANGES": "255,203,107",
    "CI-RUNNING": "0,240,255",
    "WAITING": "185,202,203",
    "APPROVED": "116,225,155",
    "DRAFT": "132,148,149",
    "MERGED": "208,188,255",
    "CLOSED": "132,148,149",
}
DEFAULT_COLOR = "185,202,203"

VIEW_FIELDS = ("state,isDraft,mergeable,reviewDecision,reviews,comments,statusCheckRollup,"
               "headRefOid,baseRefName,title,createdAt,url")
LINE_RE = re.compile(
    r"^(?:https?://github\.com/)?(?P<repo>[\w.-]+/[\w.-]+)(?:#|/pull/)(?P<num>\d+)/?$")


class GhError(Exception):
    """A gh call failed. halt is set when later calls would fail too."""

    def __init__(self, message, halt=None):
        super().__init__(message)
        self.halt = halt


def gh(*args):
    try:
        p = subprocess.run([GH, *args], capture_output=True, text=True,
                           encoding="utf-8", timeout=GH_TIMEOUT)
    except FileNotFoundError:
        raise GhError("gh not found: install the GitHub CLI or set PR_WIDGET_GH",
                      halt="gh missing")
    except subprocess.TimeoutExpired:
        raise GhError("gh timed out")
    if p.returncode != 0:
        full = (p.stderr or p.stdout or "gh failed").strip()
        halt = None
        if re.search(r"rate limit", full, re.I):
            halt = "rate limit"
        elif re.search(r"gh auth login|HTTP 401|Bad credentials|not logged in", full, re.I):
            halt = "not logged in"
        raise GhError(full.splitlines()[0][:200], halt=halt)
    return p.stdout


def load_filter():
    with open(os.path.join(HERE, "pr_status.jq"), encoding="utf-8") as f:
        return " ".join(f.read().split())


def load_seen(state_path):
    seen = {}
    if not os.path.exists(state_path):
        return seen
    in_seen = False
    for enc in ("utf-16", "utf-8-sig", "cp1252"):
        try:
            with open(state_path, encoding=enc) as f:
                lines = f.readlines()
            break
        except (UnicodeError, OSError):
            continue
    else:
        return seen
    for raw in lines:
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            in_seen = (line.lower() == "[seen]")
        elif in_seen and "=" in line and not line.startswith(";"):
            k, v = line.split("=", 1)
            try:
                seen[k.strip().lower()] = int(v.strip())
            except ValueError:
                pass
    return seen


def read_list(path):
    entries, seen = [], set()
    with open(path, encoding="utf-8-sig") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith((";", "//")):
                continue
            m = LINE_RE.match(line)
            if m:
                key = f"{m['repo']}#{int(m['num'])}"
                entry = {"key": key, "repo": m["repo"], "num": int(m["num"])}
            else:
                key = line
                entry = {"key": key, "repo": None, "num": None}
            if key not in seen:
                seen.add(key)
                entries.append(entry)
    return entries


def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def count_releases(releases, created_at):
    cut = parse_ts(created_at)
    counted = eligible = 0
    for r in releases:
        if r.get("draft") or not r.get("published_at"):
            continue
        if r.get("prerelease") and not INCLUDE_PRERELEASES:
            continue
        eligible += 1
        if parse_ts(r["published_at"]) > cut:
            counted += 1
    # one page holds 100 releases: if all of them are newer, the real count may be higher
    capped = len(releases) >= 100 and counted == eligible
    return counted, capped


def fetch_pr(repo, num, flt, cache, now, seen):
    info = json.loads(gh("pr", "view", str(num), "-R", repo,
                         "--json", VIEW_FIELDS, "--jq", flt))
    created = info.get("createdAt")
    key = f"{repo}#{num}"
    seen_ts = seen.get(key.lower(), 0)
    msg_dates = list(info.get("msg_dates") or [])

    entry = {
        "key": key, "repo": repo, "number": num,
        "title": info.get("title") or "", "url": info.get("url") or "",
        "status": info["status"], "created_at": created,
        "age_days": (now - parse_ts(created)).days if created else None,
        "behind": None, "releases": None, "releases_capped": False,
        "new_msgs": 0,
        "warnings": [], "fetched_at": now.isoformat(timespec="seconds"),
        "stale": False, "error": None,
    }
    if entry["status"] in TERMINAL:
        return entry

    try:
        rc = json.loads(gh("api", f"repos/{repo}/pulls/{num}/comments?per_page=100",
                           "--jq", "[.[].created_at]"))
        if isinstance(rc, list):
            msg_dates.extend(rc)
    except GhError as err:
        if err.halt:
            raise
        entry["warnings"].append(f"review comments failed: {err}")

    entry["new_msgs"] = sum(
        1 for d in msg_dates if d and parse_ts(d).timestamp() > seen_ts
    )

    head, base = info.get("headRefOid"), info.get("baseRefName")
    if head and base:
        path = f"repos/{repo}/compare/{quote(head, safe='')}...{quote(base, safe='')}"
        try:
            entry["behind"] = int(gh("api", path, "--jq", ".ahead_by").strip())
        except GhError as err:
            if err.halt:
                raise
            entry["warnings"].append(f"compare failed: {err}")
        except ValueError:
            entry["warnings"].append("compare returned a non-number")

    if created:
        try:
            if repo not in cache:
                cache[repo] = json.loads(gh(
                    "api", f"repos/{repo}/releases?per_page=100",
                    "--jq", "[.[] | {published_at, draft, prerelease}]"))
            entry["releases"], entry["releases_capped"] = count_releases(cache[repo], created)
        except GhError as err:
            if err.halt:
                raise
            entry["warnings"].append(f"releases failed: {err}")
    return entry


def error_entry(key, repo, num, message, now):
    return {
        "key": key, "repo": repo or key, "number": num, "title": key,
        "url": f"https://github.com/{repo}/pull/{num}" if repo else "",
        "status": "ERROR", "created_at": None, "age_days": None,
        "behind": None, "releases": None, "releases_capped": False,
        "new_msgs": 0,
        "warnings": [], "fetched_at": now.isoformat(timespec="seconds"),
        "stale": True, "error": message,
    }


def stale_entry(old, key, repo, num, message, now):
    if not old:
        return error_entry(key, repo, num, message, now)
    e = dict(old)
    e["stale"] = True
    e["error"] = message
    e.setdefault("new_msgs", 0)
    return e


def load_previous(path):
    try:
        with open(path, encoding="utf-8") as f:
            return {e["key"]: e for e in json.load(f).get("prs", [])}
    except (OSError, ValueError, KeyError, AttributeError):
        return {}


def write_atomic(path, text, encoding):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding=encoding, newline="") as f:
        f.write(text)
    os.replace(tmp, path)


def ensure_icon(repo, out_dir):
    """Absolute path of the owner's avatar PNG, downloading it when missing or a week old.

    GitHub repos have no icon of their own, so the owner's avatar stands in for it.
    Returns "" when there is no usable file (offline on the first run, say).
    """
    owner = repo.split("/")[0]
    folder = os.path.abspath(os.path.join(out_dir, "icons"))
    path = os.path.join(folder, re.sub(r"[^\w.-]", "_", owner) + ".png")
    try:
        if os.path.exists(path) and time.time() - os.path.getmtime(path) < ICON_MAX_AGE:
            return path
        os.makedirs(folder, exist_ok=True)
        req = urllib.request.Request(f"https://github.com/{quote(owner)}.png?size=64",
                                     headers={"User-Agent": "pr-watch-widget"})
        with urllib.request.urlopen(req, timeout=ICON_TIMEOUT) as resp:
            data = resp.read()
        if not data:
            raise ValueError("empty icon")
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except (OSError, ValueError):
        pass  # keep an older copy if there is one
    return path if os.path.exists(path) else ""


def clean(value):
    """Make a string safe for a Rainmeter variable (# and [ ] have special meaning)."""
    s = re.sub(r"\s+", " ", "" if value is None else str(value)).strip()
    return s.replace("#", "＃").replace("[", "(").replace("]", ")")


def short(text, limit):
    return text if len(text) <= limit else text[:limit - 3] + "..."


def show(value):
    return "?" if value is None else str(value)


def display_fields(e, icons):
    """The strings the skin shows for one PR, already formatted."""
    status = e["status"]
    if e["stale"] and status != "ERROR":
        status += " (STALE)"
    age = e["age_days"]
    chips = e["status"] not in TERMINAL and e["status"] != "ERROR"
    if chips:
        n = e["releases"]
        commits = f"+{show(e['behind'])} COMMITS"
        rels = "+? RELEASES" if n is None else (
            f"+{n}{'+' if e['releases_capped'] else ''} RELEASES")
        nm = e.get("new_msgs") or 0
        msgs = str(nm)
        msg_col = "210,215,225" if nm > 0 else "110,115,125"
        msg_bg = "180,185,195,55" if nm > 0 else "75,80,90,35"
    else:
        commits = rels = msgs = ""
        msg_col = "0,0,0"
        msg_bg = "0,0,0,0"
    icon = icons.get(e["repo"], "")
    return {
        "Ref": short(e["repo"], MAX_REF),
        # a single literal # (digits follow, no closing #) is safe in a Rainmeter value
        "Pr": "" if e["number"] is None else f"PR#{e['number']}",
        "PrHide": 1 if e["number"] is None else 0,
        "Title": e["title"],
        "Status": status,
        "Color": THEME.get(e["status"], DEFAULT_COLOR),
        "Age": "" if age is None else f"{age}d",
        "AgeHide": 1 if age is None else 0,
        "Commits": commits,
        "Rels": rels,
        "Chip": 1 if chips else 0,
        "Key": e["key"],
        "Msgs": msgs,
        "MsgColor": msg_col,
        "MsgBg": msg_bg,
        "Icon": icon,
        "IconHide": 0 if icon else 1,
        "Url": e["url"],
    }


BLANK_ROW = {"Ref": "", "Pr": "", "PrHide": 1, "Title": "", "Status": "", "Color": "0,0,0",
             "Age": "", "AgeHide": 1, "Commits": "", "Rels": "", "Chip": 0,
             "Key": "", "Msgs": "", "MsgColor": "0,0,0", "MsgBg": "0,0,0,0",
             "Icon": "", "IconHide": 1, "Url": ""}


def inc_text(results, local_now, halted, pad=PAD_ROWS, icons=None):
    """Rainmeter [Variables]: Count, Updated, Halted, then Ref1, Title1, ... for every row.

    The row number is at the END of each name (Repo12, not R12Repo) because that is the
    only form Rainmeter's nested-variable syntax documents. Rows are padded with blanks up
    to `pad` so the skin can always read a full window of rows.
    """
    icons = icons or {}
    lines = ["[Variables]",
             f"Updated={local_now:%H:%M}",
             f"Count={len(results)}",
             f"Halted={1 if halted else 0}"]
    for i in range(1, max(len(results), pad) + 1):
        row = display_fields(results[i - 1], icons) if i <= len(results) else BLANK_ROW
        for name, value in row.items():
            text = str(value) if name == "Pr" else clean(value)
            lines.append(f"{name}{i}={text}")
    return "\r\n".join(lines) + "\r\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", default=os.path.join(HERE, "prs.txt"))
    ap.add_argument("--out-dir", default=os.path.join(HERE, "data"))
    ap.add_argument("--state", default=os.path.normpath(os.path.join(HERE, "..", "state.inc")))
    ap.add_argument("--full", action="store_true",
                    help="also re-check merged and closed PRs")
    ap.add_argument("--pad", type=int, default=PAD_ROWS,
                    help="define at least this many rows in prs.inc")
    args = ap.parse_args()

    if not os.path.exists(args.list):
        print(f"list file not found: {args.list}", file=sys.stderr)
        return 2
    os.makedirs(args.out_dir, exist_ok=True)
    json_path = os.path.join(args.out_dir, "prs.json")
    inc_path = os.path.join(args.out_dir, "prs.inc")

    entries = read_list(args.list)
    prev = load_previous(json_path)
    state_path = os.path.abspath(os.path.join(HERE, "..", "state.inc"))
    seen = load_seen(state_path)
    flt = load_filter()
    now = datetime.now(timezone.utc)
    cache, results, halted = {}, [], None

    for e in entries:
        key, repo, num = e["key"], e["repo"], e["num"]
        old = prev.get(key)
        if repo is None:
            results.append(error_entry(key, None, None,
                                       "unrecognised line in the list file", now))
        elif old and old.get("status") in TERMINAL and not args.full:
            results.append(dict(old))
        elif halted:
            results.append(stale_entry(old, key, repo, num, f"skipped: {halted}", now))
        else:
            try:
                results.append(fetch_pr(repo, num, flt, cache, now, seen))
            except GhError as err:
                halted = err.halt or halted
                results.append(stale_entry(old, key, repo, num, str(err), now))
            except (ValueError, KeyError) as err:
                results.append(stale_entry(old, key, repo, num,
                                          f"unexpected gh output: {err}", now))

    results.sort(key=lambda r: RANK.get(r["status"], 0))
    doc = {"updated_at": now.isoformat(timespec="seconds"), "halted": halted,
           "count": len(results), "prs": results}
    write_atomic(json_path, json.dumps(doc, indent=2, ensure_ascii=False) + "\n", "utf-8")

    icons = {}
    for r in results:
        repo = r["repo"]
        if repo not in icons and REPO_RE.match(str(repo)):
            icons[repo] = ensure_icon(repo, args.out_dir)
    # utf-16 with a BOM is the encoding Rainmeter itself writes; plain utf-8 may garble titles
    write_atomic(inc_path, inc_text(results, datetime.now(), halted, args.pad, icons), "utf-16")

    stale = sum(1 for r in results if r["stale"])
    print(f"{len(results)} PRs, {stale} stale" + (f", halted: {halted}" if halted else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())