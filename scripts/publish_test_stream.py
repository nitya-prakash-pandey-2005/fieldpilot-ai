#!/usr/bin/env python
"""
Publish a test RTMP stream — stands in for the relay phone.

The production publisher is the worker's phone: Camera2 -> MediaCodec H.264 ->
RTMP muxer. This publishes a video file (or the laptop webcam) to the same RTMP
endpoint, so the whole ingest path — media server, RTSP pull, duty-cycled
analysis, dashboard push — is exercised end to end before any glasses exist.

ffmpeg comes from the imageio-ffmpeg pip package, so there is nothing to install
system-wide.

    # 1. media server
    docker compose up -d mediamtx

    # 2. publish (loops the sample footage forever, like a continuous feed)
    python scripts/publish_test_stream.py --worker W-022

    # 3. start ingestion
    curl -X POST http://127.0.0.1:8000/api/v1/stream/start \
         -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
         -d '{"worker_id":"W-022","zone_id":"A12","analysis_interval_s":5}'

    # 4. watch it
    curl http://127.0.0.1:8000/api/v1/stream/status
    # browser preview: http://127.0.0.1:8889/live/W-022
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        raise SystemExit(
            "✖ need an ffmpeg binary. Either:\n"
            "    pip install imageio-ffmpeg      (bundled, no system install)\n"
            "  or put a system ffmpeg on PATH and pass --ffmpeg ffmpeg")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--worker", default="W-022", help="becomes the RTMP stream key")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", default="1935")
    ap.add_argument("--source", default=None,
                    help="video file to publish; default is the bundled sample")
    ap.add_argument("--webcam", action="store_true",
                    help="publish the laptop webcam instead of a file")
    ap.add_argument("--no-loop", action="store_true",
                    help="publish once instead of looping forever")
    ap.add_argument("--fps", type=int, default=15,
                    help="a relay phone on site WiFi realistically manages 10-20")
    ap.add_argument("--bitrate", default="1200k",
                    help="site uplinks are poor; 1-2 Mbps is realistic")
    ap.add_argument("--ffmpeg", default=None, help="override the ffmpeg binary")
    args = ap.parse_args()

    exe = args.ffmpeg or ffmpeg_exe()
    target = f"rtmp://{args.host}:{args.port}/live/{args.worker}"

    if args.webcam:
        # dshow is Windows-specific; the equivalents are avfoundation (macOS)
        # and v4l2 (Linux).
        if not sys.platform.startswith("win"):
            raise SystemExit("--webcam is wired for Windows dshow; on macOS use "
                             "-f avfoundation, on Linux -f v4l2")
        source_args = ["-f", "dshow", "-i", "video=Integrated Camera"]
    else:
        src = Path(args.source) if args.source else REPO / "data" / "sample_construction.mp4"
        if not src.exists():
            raise SystemExit(f"✖ source not found: {src}")
        source_args = []
        if not args.no_loop:
            # -stream_loop must precede -i. Looping makes the file behave like a
            # continuous feed, which is what the ingestor is designed for.
            source_args += ["-stream_loop", "-1"]
        # Pace the file at wall-clock speed; without this ffmpeg pushes the whole
        # file as fast as it can and the "stream" ends in a second.
        source_args += ["-re", "-i", str(src)]

    cmd = [
        exe, "-hide_banner", "-loglevel", "warning",
        *source_args,
        "-c:v", "libx264",
        "-preset", "veryfast",          # a phone has no time for a slow preset
        "-tune", "zerolatency",         # no lookahead: this is a live feed
        "-pix_fmt", "yuv420p",          # required for broad decoder support
        "-r", str(args.fps),
        "-g", str(args.fps * 2),        # keyframe every 2s so consumers can join quickly
        "-b:v", args.bitrate,
        "-maxrate", args.bitrate,
        "-bufsize", "2M",
        "-an",                          # audio goes over the separate voice path
        "-f", "flv",                    # RTMP's container
        target,
    ]

    print(f"▶ publishing to {target}")
    print(f"  source   : {'webcam' if args.webcam else (args.source or 'data/sample_construction.mp4')}")
    print(f"  encoding : H.264 {args.fps}fps {args.bitrate}, zerolatency")
    print(f"  loop     : {not args.no_loop}")
    print("\n  Consume it with:")
    print(f"    rtsp://{args.host}:8554/live/{args.worker}      (vision pipeline)")
    print(f"    http://{args.host}:8889/live/{args.worker}      (browser preview)")
    print("\n  Ctrl+C to stop.\n")

    try:
        return subprocess.call(cmd)
    except KeyboardInterrupt:
        print("\n  stopped")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
