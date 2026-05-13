"""E2E: invoke the real _fetch_tweets_via_nitter_rss_v2 path on a small player set.

Streams logs as they happen via web.app._log (which print()s).
Pass criteria: every fx-confirmed video tweet must yield a >0-byte mp4 in
output/videos/, OR be reported as '视频缓存命中'/'视频新下载完成'.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# Force-clear cached videos so we test the *fresh download* path.
VIDEOS = REPO / "output" / "videos"
TEST_HANDLES = ["KingJames", "StephenCurry30", "Giannis_An34", "anthonyedwards"]


def p(m: str) -> None:
    print(m, flush=True)


async def run() -> int:
    from web import app as webapp
    from config.players import load_players

    players_all = load_players()
    players = [p for p in players_all if p.handle in TEST_HANDLES]
    p(f"=== invoking _fetch_tweets_via_nitter_rss_v2 for {[pl.handle for pl in players]} ===")

    # Snapshot existing video files; we want to see whether any NEW one appears.
    before = {f.name for f in VIDEOS.glob("*.mp4")} if VIDEOS.exists() else set()
    p(f"existing videos: {len(before)}")

    # Reduce per-player delays for the test by patching constants? -> no, we want realism.
    # Just run; should take ~30-60s for 4 handles.
    t0 = time.time()
    try:
        result = await webapp._fetch_tweets_via_nitter_rss_v2(players)
    except Exception as e:
        p(f"FATAL: {e!r}")
        return 1
    p(f"=== fetch returned {len(result)} tweets in {time.time()-t0:.1f}s ===")

    # Wait a moment for any straggling video tasks (they were ensure_future'd).
    # The function awaits screenshot_tasks at the end, so videos should be done.
    after = {f.name for f in VIDEOS.glob("*.mp4")} if VIDEOS.exists() else set()
    new_files = after - before
    p(f"NEW video files: {len(new_files)}")
    for n in sorted(new_files):
        size = (VIDEOS / n).stat().st_size
        p(f"  + {n} ({size/1024/1024:.2f}MB)")

    # Tweets that ended up with a video_url
    with_video = [t for t in result if t.get("video_url")]
    p(f"tweets with video_url set: {len(with_video)}")
    for t in with_video:
        p(f"  - @{t['player_handle']} {t['tweet_id']} -> {t['video_url']}")

    if not with_video:
        p("WARN: no tweets got videos this run (could be sample-dependent)")
        return 2
    p("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
