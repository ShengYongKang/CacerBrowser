"""Download the Camoufox engine zip via a GitHub release mirror, then run
camoufox's own install flow (release resolution, sha256 verify, unzip,
version.json, activation) untouched.

Why this exists: direct GitHub is unusable from this network, the local
SOCKS5 proxy's exit gets throttled by the GitHub CDN to ~0-260 KB/s, while
the gh-proxy.com release mirror measured 65 MB/s direct.

Usage:
  python tools/fetch_engine.py [--mirror-base https://gh-proxy.com/]

Integrity: camoufox verifies the GitHub-provided sha256 digest of the
assembled zip before extracting, so a truncated or tampered mirror download
fails the install instead of shipping a broken engine.
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

CURL = "curl.exe"  # ships with Windows 10/11


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mirror-base", default="https://gh-proxy.com/")
    ap.add_argument("--workdir", default=None)
    args = ap.parse_args()

    # The mirror is reached directly; never let ambient proxy env leak in.
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        os.environ.pop(key, None)

    import camoufox.pkgman as pm

    workdir = Path(args.workdir or (Path.home() / ".cache" / "shadowfox-fetch"))
    workdir.mkdir(parents=True, exist_ok=True)
    zip_path = workdir / "engine.zip"

    def log(msg: str) -> None:
        print(f"[fetch_engine] {msg}", flush=True)

    def mirror_webdl(url, desc=None, buffer=None, bar=True, progress_callback=None):
        target = args.mirror_base.rstrip("/") + "/" + url

        # Best-effort expected size from a HEAD (mirrors may not honor it).
        expected = 0
        try:
            out = subprocess.run(
                [CURL, "--noproxy", "*", "-sSI", "-m", "20", target],
                capture_output=True, text=True, timeout=30,
            )
            for line in out.stdout.splitlines():
                if line.lower().startswith("content-length:"):
                    expected = int(line.split(":", 1)[1].strip())
        except Exception:
            pass

        # The mirror ignores Range headers (returns 200 full-body), so resume is
        # impossible: each attempt is a fresh transfer, aborted if it stalls
        # below 10 KB/s for 30s. camoufox's sha256 check catches corruption.
        for attempt in range(20):
            log(f"downloading (attempt {attempt + 1}) -> {target}")
            t0 = time.time()
            proc = subprocess.run(
                [CURL, "--noproxy", "*", "-sSL", "-o", str(zip_path),
                 "--connect-timeout", "20", "--speed-limit", "10240",
                 "--speed-time", "30", target],
                capture_output=True, text=True,
            )
            if proc.returncode == 0 and zip_path.exists():
                size = zip_path.stat().st_size
                if expected and size != expected:
                    log(f"size mismatch: {size} != {expected}, retrying")
                    continue
                log(f"downloaded {size / 1e6:.0f} MB in {time.time() - t0:.0f}s")
                break
            log(f"curl rc={proc.returncode} {proc.stderr.strip()[:200]}, retry in 5s")
            time.sleep(5)
        else:
            raise RuntimeError(f"could not download {target}")

        if buffer is None:
            raise RuntimeError("camoufox called webdl without a buffer")
        with open(zip_path, "rb") as f:
            while True:
                block = f.read(1 << 24)
                if not block:
                    break
                buffer.write(block)
        buffer.seek(0)
        return buffer

    pm.webdl = mirror_webdl

    fetcher = pm.CamoufoxFetcher()
    fetcher.install()
    zip_path.unlink(missing_ok=True)
    log("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
