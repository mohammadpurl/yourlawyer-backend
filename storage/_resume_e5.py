"""Resumable download of multilingual-e5-base weights with retries."""
from __future__ import annotations

import os
import time
import urllib.error
import urllib.request
from pathlib import Path

EXPECTED = 1_112_201_288
OUT = Path("storage/models/multilingual-e5-base/model.safetensors")
URLS = [
    "https://hf-mirror.com/intfloat/multilingual-e5-base/resolve/main/model.safetensors",
    "https://huggingface.co/intfloat/multilingual-e5-base/resolve/main/model.safetensors",
]


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    url_i = 0
    while True:
        have = OUT.stat().st_size if OUT.exists() else 0
        if have >= EXPECTED:
            # validate header
            with OUT.open("rb") as f:
                head = f.read(64)
            if any(b != 0 for b in head) and have == EXPECTED:
                print(f"COMPLETE size={have}", flush=True)
                return 0
            print("size ok but header bad — deleting", flush=True)
            OUT.unlink()
            continue

        url = URLS[url_i % len(URLS)]
        print(f"resume {have}/{EXPECTED} via {url}", flush=True)
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0", "Range": f"bytes={have}-"},
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                print(
                    f"status={resp.status} range={resp.headers.get('Content-Range')}",
                    flush=True,
                )
                mode = "ab" if resp.status == 206 else "wb"
                if resp.status != 206:
                    have = 0
                t0 = time.time()
                total = have
                with OUT.open(mode) as f:
                    while True:
                        chunk = resp.read(1024 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        total += len(chunk)
                        if total % (25 * 1024 * 1024) < 1024 * 1024:
                            dt = max(time.time() - t0, 1)
                            pct = 100.0 * total / EXPECTED
                            print(
                                f"bytes={total} pct={pct:.1f}% "
                                f"speed={(total - have) / dt / 1e6:.2f}MB/s",
                                flush=True,
                            )
        except Exception as e:
            print(f"ERR {type(e).__name__}: {e} — retry in 5s", flush=True)
            url_i += 1
            time.sleep(5)
            continue

        # connection ended early — loop to resume
        have2 = OUT.stat().st_size if OUT.exists() else 0
        if have2 < EXPECTED:
            print(f"incomplete after stream end ({have2}); continuing", flush=True)
            url_i += 1
            time.sleep(2)


if __name__ == "__main__":
    raise SystemExit(main())
