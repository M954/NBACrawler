"""E2E: verify every tweet that actually has a video gets downloaded.

Runs standalone (no pytest, no Flask). Prints progress per-tweet with flush.
Exit code != 0 if any fx-confirmed video failed to download.
"""
from __future__ import annotations

import json
import random
import sys
import tempfile
import time
import urllib.request
import urllib.error
from pathlib import Path
from xml.etree import ElementTree

NITTER_RSS_INSTANCES = [
    "https://nitter.net",
    "https://nitter.poast.org",
    "https://nitter.privacydev.net",
    "https://xcancel.com",
]
UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
]

REPO = Path(__file__).resolve().parent.parent
PLAYERS = json.loads((REPO / "config" / "players.json").read_text(encoding="utf-8"))
SAMPLE = [p["handle"] for p in PLAYERS[:8]]


def p(msg: str) -> None:
    print(msg, flush=True)


def fetch_rss(handle: str) -> str | None:
    for inst in NITTER_RSS_INSTANCES:
        url = f"{inst}/{handle}/rss"
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": random.choice(UA_LIST),
                "Accept": "application/rss+xml, application/xml, text/xml",
            })
            r = urllib.request.urlopen(req, timeout=15)
            data = r.read().decode("utf-8", errors="replace")
            if len(data) > 500 and "<item>" in data:
                p(f"  RSS ok via {inst} ({len(data)} bytes)")
                return data
            p(f"  RSS empty/short via {inst} ({len(data)} bytes)")
        except urllib.error.HTTPError as e:
            p(f"  RSS HTTP {e.code} via {inst}")
        except Exception as e:
            p(f"  RSS err via {inst}: {str(e)[:60]}")
    return None


def parse_items(rss: str, max_items: int = 3) -> list[dict]:
    out = []
    root = ElementTree.fromstring(rss)
    for item in root.findall(".//item")[: max_items * 4]:
        link = item.find("link")
        link_text = link.text.strip() if link is not None and link.text else ""
        if "/status/" not in link_text:
            continue
        tid = link_text.split("/status/")[-1].split("#")[0].split("?")[0]
        if not tid.isdigit():
            continue
        title_el = item.find("title")
        title = title_el.text.strip() if title_el is not None and title_el.text else ""
        if title.startswith("RT by"):
            continue
        desc_el = item.find("description")
        desc = desc_el.text if desc_el is not None and desc_el.text else ""
        out.append({"tid": tid, "title": title[:60], "desc": desc, "rss_marker": ">Video<" in desc})
        if len(out) >= max_items:
            break
    return out


def fx_video_url(handle: str, tid: str) -> tuple[bool, str | None, str]:
    """Return (fx_says_video, video_url, note)."""
    url = f"https://api.fxtwitter.com/{handle}/status/{tid}"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": random.choice(UA_LIST),
            "Accept": "application/json",
        })
        r = urllib.request.urlopen(req, timeout=15)
        data = json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception as e:
        return False, None, f"fx_err:{str(e)[:50]}"
    tw = data.get("tweet") or {}
    media_all = (tw.get("media") or {}).get("all") or []
    for m in media_all:
        if m.get("type") == "video" and m.get("url"):
            return True, m["url"], f"fx_video ({len(media_all)} media)"
    if media_all:
        kinds = ",".join(m.get("type", "?") for m in media_all)
        return False, None, f"fx_no_video (media: {kinds})"
    return False, None, "fx_no_media"


def download(url: str, dest: Path) -> tuple[bool, str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": random.choice(UA_LIST)})
        r = urllib.request.urlopen(req, timeout=60)
        with open(dest, "wb") as f:
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                f.write(chunk)
        size = dest.stat().st_size
        if size < 10_000:
            return False, f"too_small:{size}"
        return True, f"{size/1024/1024:.2f}MB"
    except Exception as e:
        return False, f"dl_err:{str(e)[:60]}"


def main() -> int:
    p(f"=== E2E video scrape test ===  handles: {SAMPLE}")
    tmp = Path(tempfile.mkdtemp(prefix="nba_e2e_"))
    p(f"tmp dir: {tmp}")

    failures: list[str] = []
    fx_video_count = 0
    fx_video_downloaded = 0
    rss_marker_count = 0

    for i, handle in enumerate(SAMPLE, 1):
        p(f"\n[{i}/{len(SAMPLE)}] @{handle}")
        rss = fetch_rss(handle)
        if not rss:
            p(f"  SKIP: no RSS")
            continue
        items = parse_items(rss, max_items=2)
        if not items:
            p(f"  SKIP: no original tweet items in RSS")
            continue
        for it in items:
            tid = it["tid"]
            marker = it["rss_marker"]
            if marker:
                rss_marker_count += 1
            t0 = time.time()
            fx_says, vurl, note = fx_video_url(handle, tid)
            p(f"  tid={tid} rss_marker={marker} {note} ({time.time()-t0:.1f}s)")
            if fx_says:
                fx_video_count += 1
                dest = tmp / f"tweet_{tid}.mp4"
                t0 = time.time()
                ok, info = download(vurl, dest)
                p(f"    DOWNLOAD {'OK' if ok else 'FAIL'} {info} ({time.time()-t0:.1f}s)")
                if ok:
                    fx_video_downloaded += 1
                else:
                    failures.append(f"@{handle} {tid}: {info}")
        time.sleep(random.uniform(2.0, 4.0))

    p("\n=== SUMMARY ===")
    p(f"rss_marker_present: {rss_marker_count}")
    p(f"fx_confirmed_video: {fx_video_count}")
    p(f"downloaded_ok: {fx_video_downloaded}")
    if failures:
        p(f"FAILURES ({len(failures)}):")
        for f in failures:
            p(f"  - {f}")
        return 1
    if fx_video_count == 0:
        p("WARN: no videos found in sample — cannot prove download path works")
        return 2
    p("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
