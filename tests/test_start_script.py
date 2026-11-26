import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STANDALONE = ROOT / "web" / ".next" / "standalone"
ROUTES = ["/", "/people", "/person", "/uplift", "/uplift/person", "/ai-year", "/rankings", "/qa", "/ask",
          "/selection", "/teams", "/sources", "/settings"]

pytestmark = [
    pytest.mark.skipif(os.environ.get("RUN_SLOW") != "1", reason="slow: set RUN_SLOW=1"),
    pytest.mark.skipif(not (STANDALONE / "server.js").exists(), reason="web/.next/standalone missing; run npm run build"),
]


def _free(port):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def _get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=30) as r:
        return r.status, r.headers.get("content-type", ""), r.read()


def _children(pid):
    out = subprocess.run(["pgrep", "-P", str(pid)], capture_output=True, text=True).stdout.split()
    return [int(p) for p in out]


def test_start_script_serves_pages_and_api(tmp_path):
    if not _free(8001):
        pytest.skip("port 8001 is busy (the Next rewrite is built for it)")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    cli = shutil.which("delivery-analysis") or str(Path(sys.executable).with_name("delivery-analysis"))
    env = dict(os.environ, PORT=str(port), GITHUB_ANALYSIS_RESULTS=str(tmp_path), DA_CMD=cli)
    proc = subprocess.Popen(["bash", str(ROOT / "scripts" / "start.sh")], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.time() + 90
        while True:
            try:
                _get(port, "/api/version")
                break
            except Exception:
                if proc.poll() is not None or time.time() > deadline:
                    pytest.fail("start.sh did not become ready")
                time.sleep(1)
        for route in ROUTES:
            status, kind, _ = _get(port, route)
            assert status == 200, route
            assert "text/html" in kind, route
        status, kind, body = _get(port, "/api/version")
        assert "json" in kind
        assert "version" in json.loads(body)

        api_pids = [p for p in _children(proc.pid) if "serve" in Path(f"/proc/{p}/cmdline").read_text().replace("\0", " ")]
        assert api_pids, "FastAPI child not found"
        os.kill(api_pids[0], signal.SIGKILL)
        assert proc.wait(timeout=30) != 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
