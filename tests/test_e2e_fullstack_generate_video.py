"""Full-stack E2E: drive the existing NBACrawler dashboard UI with Playwright,
trigger the bulk "生成视频" flow against a stubbed NBAVedio backend, and assert
on the P1/P4/P5 trace artifacts written by the pipeline.

This test does NOT introduce new UI / endpoints — it only exercises:
  NBACrawler index.html (.tweet-checkbox + #btn-video)
    -> POST /api/generate-videos
    -> Crawler background thread POSTs multipart to http://localhost:8000/generate-ai
    -> NBAVedio pipeline runs in STUB mode (NBAVEDIO_E2E_STUB=1)
    -> writes output/traces/{tid}.jsonl  (P1 judge_agreement + P4 llm_call)
       and output/traces/{tid}_prompts.jsonl (P5 untrusted wrapping)

Both servers are started as subprocesses on fixed ports (5000 + 8000). The
fixture tweet is appended to NBACrawler/output/tweets.json and removed in
teardown. The dummy cover JPG and trace artifacts are also cleaned up.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

NBACRAWLER_DIR = Path(__file__).resolve().parent.parent
NBAVEDIO_DIR = NBACRAWLER_DIR.parent / "NBAVedio"

TWEETS_FILE = NBACRAWLER_DIR / "output" / "tweets.json"
COVERS_DIR = NBACRAWLER_DIR / "output" / "covers"
TRACES_DIR = NBAVEDIO_DIR / "output" / "traces"

FIXTURE_TID = "e2e_fixture_001"
FIXTURE_COVER_NAME = f"{FIXTURE_TID}.jpg"

CRAWLER_PORT = 5057
VIDEO_PORT = 8057
CRAWLER_URL = f"http://127.0.0.1:{CRAWLER_PORT}"
VIDEO_URL = f"http://127.0.0.1:{VIDEO_PORT}"


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _wait_http(url: str, timeout: float = 40.0) -> None:
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status < 500:
                    return
        except Exception as e:  # noqa: BLE001
            last_err = e
        time.sleep(0.5)
    raise RuntimeError(f"server at {url} did not become ready: {last_err}")


def _make_fixture_cover() -> None:
    """Create a tiny black JPG for the fixture tweet cover."""
    COVERS_DIR.mkdir(parents=True, exist_ok=True)
    dst = COVERS_DIR / FIXTURE_COVER_NAME
    if dst.exists():
        return
    try:
        from PIL import Image
        Image.new("RGB", (100, 100), (0, 0, 0)).save(dst, "JPEG", quality=70)
    except Exception:
        # Minimal JPEG header bytes; downstream only reads bytes for multipart.
        dst.write_bytes(bytes.fromhex(
            "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707"
            "07090908"
        ) + b"\xff\xd9")


def _inject_fixture_tweet() -> dict:
    """Prepend fixture tweet to tweets.json. Returns original file bytes for restore."""
    original = TWEETS_FILE.read_bytes() if TWEETS_FILE.exists() else b"[]"
    try:
        tweets = json.loads(original.decode("utf-8") or "[]")
    except Exception:
        tweets = []
    # remove any existing fixture by id
    tweets = [t for t in tweets if t.get("tweet_id") != FIXTURE_TID]
    fixture = {
        "tweet_id": FIXTURE_TID,
        "player_name": "E2E Fixture",
        "player_handle": "e2e_fixture",
        "content": "E2E fixture tweet content (do not translate).",
        "content_cn": "E2E 夹具推文内容（请勿翻译）。",
        "url": f"https://x.com/e2e_fixture/status/{FIXTURE_TID}",
        "media_urls": [],
        "cover_image_path": f"covers/{FIXTURE_COVER_NAME}",
        "video_url": None,
        "retweet_count": 0,
        "like_count": 0,
        "reply_count": 0,
        "tweet_type": "original",
        "tweet_date": "2026-05-25T00:00:00+00:00",
        "scraped_at": "2026-05-25T00:00:00+00:00",
        "translation_status": "completed",
    }
    tweets.insert(0, fixture)
    TWEETS_FILE.write_text(json.dumps(tweets, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"original": original}


def _restore_tweets(snapshot: dict) -> None:
    TWEETS_FILE.write_bytes(snapshot["original"])


def _cleanup_artifacts() -> None:
    for p in (
        TRACES_DIR / f"{FIXTURE_TID}.jsonl",
        TRACES_DIR / f"{FIXTURE_TID}_prompts.jsonl",
        COVERS_DIR / FIXTURE_COVER_NAME,
    ):
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass


@pytest.fixture(scope="module")
def servers():
    if not _port_free(CRAWLER_PORT):
        pytest.skip(f"port {CRAWLER_PORT} busy")
    if not _port_free(VIDEO_PORT):
        pytest.skip(f"port {VIDEO_PORT} busy")

    _make_fixture_cover()
    snapshot = _inject_fixture_tweet()
    # Pre-delete any stale trace from a previous run.
    for p in (TRACES_DIR / f"{FIXTURE_TID}.jsonl", TRACES_DIR / f"{FIXTURE_TID}_prompts.jsonl"):
        if p.exists():
            p.unlink()
    TRACES_DIR.mkdir(parents=True, exist_ok=True)

    # Start NBAVedio (stubbed)
    video_env = os.environ.copy()
    video_env["NBAVEDIO_E2E_STUB"] = "1"
    video_env["AI_BACKEND"] = "claude"  # avoid GPT key check; stub bypasses _call anyway
    video_env["PYTHONUNBUFFERED"] = "1"
    # tweet_api binds 0.0.0.0:8000 hardcoded; we override by launching via uvicorn module.
    video_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "tweet_api:app",
         "--host", "127.0.0.1", "--port", str(VIDEO_PORT)],
        cwd=str(NBAVEDIO_DIR),
        env=video_env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )

    # Start NBACrawler Flask. Patch the hardcoded localhost:8000 by env override?
    # The crawler hits "http://localhost:8000/generate-ai" hardcoded. We must
    # use 8000 then. Re-check that 8000 is free; if not, monkeypatch via a shim.
    crawler_env = os.environ.copy()
    crawler_env["PYTHONUNBUFFERED"] = "1"
    crawler_env["NBAVEDIO_E2E_URL"] = VIDEO_URL  # informational only
    # Ensure NBACrawler/ is on PYTHONPATH so sitecustomize.py (URL shim) auto-loads.
    existing_pp = crawler_env.get("PYTHONPATH", "")
    crawler_env["PYTHONPATH"] = (
        str(NBACRAWLER_DIR) + (os.pathsep + existing_pp if existing_pp else "")
    )
    crawler_proc = subprocess.Popen(
        [sys.executable, "-m", "web.app", "--host", "127.0.0.1", "--port", str(CRAWLER_PORT)],
        cwd=str(NBACRAWLER_DIR),
        env=crawler_env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )

    try:
        _wait_http(f"{VIDEO_URL}/health", timeout=40)
        _wait_http(f"{CRAWLER_URL}/api/tweets", timeout=40)
        yield {"video": video_proc, "crawler": crawler_proc}
    finally:
        for p in (crawler_proc, video_proc):
            try:
                p.terminate()
                p.wait(timeout=8)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
        _restore_tweets(snapshot)
        _cleanup_artifacts()


def _patch_crawler_video_url() -> None:
    """The crawler hardcodes http://localhost:8000/generate-ai. For this e2e we run
    the video service on VIDEO_PORT to avoid colliding with a real instance on 8000.
    We monkeypatch web/app.py at runtime by setting an env var the test will
    enforce via a pre-import shim — see conftest hook below."""
    # implemented via _patch.py written by the fixture; see SHIM_PATH usage.


# --- Runtime shim: rewrite the hardcoded URL in the crawler before it spins up.
# We achieve this by writing a sitecustomize-style shim into NBACrawler that
# patches urllib.request.Request when URL == "http://localhost:8000/generate-ai".
SHIM_PATH = NBACRAWLER_DIR / "_e2e_url_shim.py"


@pytest.fixture(scope="module", autouse=True)
def install_url_shim():
    """Make web.app use our VIDEO_URL instead of the hardcoded http://localhost:8000."""
    shim = f'''
import urllib.request as _u
_orig_Request = _u.Request

def _patched_Request(url, *a, **kw):
    if isinstance(url, str) and url.startswith("http://localhost:8000/"):
        url = url.replace("http://localhost:8000", "{VIDEO_URL}")
    return _orig_Request(url, *a, **kw)

_u.Request = _patched_Request
'''
    SHIM_PATH.write_text(shim, encoding="utf-8")
    # Inject into web/app.py boot via PYTHONSTARTUP-like trick: create sitecustomize
    # in NBACrawler that imports the shim, and add NBACrawler to PYTHONPATH for the
    # subprocess (we already use cwd=NBACrawler so sitecustomize works if on sys.path).
    sitecustomize = NBACRAWLER_DIR / "sitecustomize.py"
    sitecustomize.write_text(
        "import _e2e_url_shim  # NBA E2E test url rewrite\n", encoding="utf-8"
    )
    try:
        yield
    finally:
        for p in (SHIM_PATH, sitecustomize):
            try:
                p.unlink()
            except Exception:
                pass


def test_fullstack_generate_video_e2e(servers):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(CRAWLER_URL, wait_until="domcontentloaded")
        # Diagnostics: fetch /api/tweets to confirm seeded fixture is visible.
        with urllib.request.urlopen(f"{CRAWLER_URL}/api/tweets", timeout=5) as r:
            api_tweets = json.loads(r.read().decode("utf-8"))
        ids_visible = [t.get("tweet_id") for t in api_tweets][:5]
        print(f"[e2e] /api/tweets returned {len(api_tweets)} tweets, first ids={ids_visible}")
        assert any(t.get("tweet_id") == FIXTURE_TID for t in api_tweets), \
            f"fixture tweet not in /api/tweets payload (got {len(api_tweets)})"
        # The frontend default date filter is 'today' — force 'all' so our fixture shows
        # regardless of the browser-local date the test runs on.
        page.evaluate("() => { _dateFilter = {mode:'all', value:null}; filterTweets(); }")
        # Wait for the tweet checkbox for our fixture to appear.
        sel = f'.tweet-checkbox[data-tid="{FIXTURE_TID}"]'
        try:
            page.wait_for_selector(sel, timeout=15000)
        except Exception:
            html = page.content()
            (Path(__file__).parent / "_e2e_failure.html").write_text(html, encoding="utf-8")
            raise
        page.check(sel)
        # Click the bulk-generate button (id=btn-video).
        page.wait_for_function("() => !document.getElementById('btn-video').disabled", timeout=5000)
        page.click("#btn-video")

        # Poll the video-status endpoint and the trace file presence.
        trace_path = TRACES_DIR / f"{FIXTURE_TID}.jsonl"
        prompts_path = TRACES_DIR / f"{FIXTURE_TID}_prompts.jsonl"

        deadline = time.time() + 90
        last_status = ""
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"{CRAWLER_URL}/api/video-status", timeout=2) as r:
                    st = json.loads(r.read().decode("utf-8"))
                    last_status = st.get("status", "")
            except Exception:
                last_status = "err"
            if last_status == "idle" and trace_path.exists():
                break
            time.sleep(1.0)

        browser.close()

    # ---- assertions on artifacts (P1, P4, P5) ----
    if not trace_path.exists():
        # Diagnostics: dump last bits of subprocess output and video logs.
        try:
            with urllib.request.urlopen(f"{VIDEO_URL}/logs?limit=80", timeout=3) as r:
                vlogs = r.read().decode("utf-8")
            print(f"[e2e] video /logs tail:\n{vlogs[-3000:]}")
        except Exception as e:
            print(f"[e2e] could not fetch video logs: {e}")
        try:
            with urllib.request.urlopen(f"{CRAWLER_URL}/api/video-status", timeout=3) as r:
                print(f"[e2e] final crawler video-status: {r.read().decode('utf-8')}")
        except Exception as e:
            print(f"[e2e] could not fetch crawler status: {e}")
        # drain crawler subprocess stdout
        try:
            crawler = servers["crawler"]
            crawler.terminate()
            out, _ = crawler.communicate(timeout=5)
            print(f"[e2e] crawler stdout tail:\n{out.decode('utf-8', errors='replace')[-3000:]}")
        except Exception as e:
            print(f"[e2e] could not drain crawler: {e}")
    assert trace_path.exists(), f"trace file missing: {trace_path}"
    events = []
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        events.append(json.loads(line))
    steps = [e.get("step") for e in events]
    assert "pipeline_start" in steps, f"no pipeline_start; steps={steps}"
    assert "pipeline_end" in steps, f"no pipeline_end; steps={steps}"

    # P4: llm_call events with proper fields
    llm_calls = [e for e in events if e.get("step") == "llm_call"]
    assert llm_calls, "expected at least one llm_call event"
    for e in llm_calls[:3]:
        assert "model" in e and "tokens_in_est" in e and "tokens_out_est" in e, e

    # P1: judge_agreement event with content_issues_jaccard field
    judge_evts = [e for e in events if e.get("step") == "judge_agreement"]
    if not judge_evts:
        # judge_agreement may be embedded in another step's payload (e.g. round_end).
        embedded = [e for e in events if "content_issues_jaccard" in json.dumps(e, ensure_ascii=False)]
        assert embedded, f"no judge_agreement signal in trace; steps={steps}"
    else:
        ja = judge_evts[0]
        assert "content_issues_jaccard" in ja, ja

    # P5: prompts log has at least one <untrusted_*> wrapping
    assert prompts_path.exists(), f"prompts file missing: {prompts_path}"
    body = prompts_path.read_text(encoding="utf-8")
    assert "<untrusted_" in body, "no untrusted_ wrapping found in any prompt"
