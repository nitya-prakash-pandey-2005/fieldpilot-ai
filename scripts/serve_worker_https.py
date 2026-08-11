#!/usr/bin/env python
"""
Serve the dashboard over HTTPS so a phone will act as the worker's glasses.

A phone refuses camera and microphone access on a plain http:// origin — that is
a browser security rule, not a setting — so the Worker View is unusable over the
LAN until the page is served over TLS. This generates a certificate that covers
this machine's current LAN address and starts the dev server with it.

Run it again whenever the laptop joins a different network. The LAN IP changes,
and a certificate that does not name the address you typed produces a harsher
browser warning than an untrusted-issuer one -- some mobile browsers refuse to
offer a "proceed" option at all for a name mismatch.

    python scripts/serve_worker_https.py            # regenerate cert + serve
    python scripts/serve_worker_https.py --print    # just show the phone URL

WHAT THIS DOES NOT DO. It cannot open the Windows Firewall, and it cannot defeat
client isolation on a campus or guest network. Both are covered in the checklist
it prints, because both fail in the same confusing way: the page simply never
loads on the phone while working perfectly on the laptop.
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parents[1] / "frontend" / "engineer-dashboard"
CERT_DIR = DASHBOARD / "certificates"
CERT = CERT_DIR / "localhost.pem"
KEY = CERT_DIR / "localhost-key.pem"
PORT = int(os.getenv("DASHBOARD_PORT", "3000"))


def lan_addresses() -> list[str]:
    """Private IPv4 addresses of this machine, the routable one first.

    Ordering is decided by which interface actually carries the default route,
    not by guessing from the prefix. An earlier version treated every 172.x
    address as a virtual adapter, on the theory that WSL and Docker leave
    bridges behind — but 172.16/12 is a legitimate private range, and on this
    machine the real Wi-Fi sits at 172.16.20.88 while the WSL bridge is at
    172.26.128.1. Prefix-guessing would have offered the phone an address
    reachable from nothing.
    """
    found: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except OSError:
        pass

    # The source address the OS picks for an external destination is the one on
    # the default route — i.e. the interface a phone on the same network shares.
    # UDP connect() assigns a local address without sending a packet.
    primary: str | None = None
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            primary = s.getsockname()[0]
            found.add(primary)
    except OSError:
        pass

    def usable(ip: str) -> bool:
        a = ipaddress.IPv4Address(ip)
        return a.is_private and not a.is_loopback and not a.is_link_local

    ordered = sorted(ip for ip in found if usable(ip))
    if primary and primary in ordered:
        ordered.remove(primary)
        ordered.insert(0, primary)
    return ordered


def find_mkcert() -> str | None:
    on_path = shutil.which("mkcert")
    if on_path:
        return on_path
    # Next.js downloads its own copy the first time --experimental-https runs.
    local = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "mkcert"
    if local.is_dir():
        for p in sorted(local.iterdir()):
            if p.name.startswith("mkcert") and p.is_file():
                return str(p)
    return None


def regenerate(hosts: list[str]) -> bool:
    mkcert = find_mkcert()
    if not mkcert:
        print("! mkcert not found. Run `npx next dev --experimental-https` once to fetch it.")
        return False

    CERT_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [mkcert, "-cert-file", CERT.name, "-key-file", KEY.name,
           "localhost", "127.0.0.1", "::1", "0.0.0.0", *hosts]
    print(f"  generating certificate for: {', '.join(['localhost', *hosts])}")
    r = subprocess.run(cmd, cwd=CERT_DIR, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"! mkcert failed: {r.stderr.strip()[:300]}")
        return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", action="store_true", dest="print_only",
                    help="show the phone URL and checklist, do not start the server")
    args = ap.parse_args()

    ips = lan_addresses()
    if not ips:
        print("! No private LAN address found. Is Wi-Fi connected?")
        return 1

    primary = ips[0]
    url = f"https://{primary}:{PORT}/worker"

    print("\nFieldPilot — Worker View over HTTPS")
    print("=" * 60)
    print(f"  Phone URL : {url}")
    if len(ips) > 1:
        print(f"  (others   : {', '.join(f'https://{ip}:{PORT}/worker' for ip in ips[1:])})")
    print(f"  Sign in as: worker@fieldpilot.demo")
    print("=" * 60)
    print("""
If the page does not load on the phone, it is almost always one of these two,
and both look identical from the phone — an endless spinner:

  1. Windows Firewall has no inbound rule for this port. Run ONCE, in an
     Administrator PowerShell:

       New-NetFirewallRule -DisplayName "FieldPilot dashboard" -Direction Inbound `
         -LocalPort {port} -Protocol TCP -Action Allow -Profile Private,Public

  2. The network isolates its clients. Campus, guest and hotel Wi-Fi commonly
     block device-to-device traffic entirely, and no firewall rule can undo it.
     Turn on the PHONE's hotspot and connect this laptop to it, then re-run this
     script — the address will have changed and the certificate has to name it.

The certificate is signed by a local authority the phone does not know, so it
will warn once. Accept it ("Advanced" -> "Proceed"). The origin then counts as
secure, which is what unlocks the camera and microphone.
""".replace("{port}", str(PORT)))

    if args.print_only:
        return 0

    if not regenerate(ips):
        return 1

    print(f"\n  starting dev server on 0.0.0.0:{PORT} (ctrl-c to stop)\n")
    npx = "npx.cmd" if os.name == "nt" else "npx"
    return subprocess.call(
        [npx, "next", "dev", "--experimental-https",
         "--experimental-https-cert", str(CERT), "--experimental-https-key", str(KEY),
         "--hostname", "0.0.0.0", "--port", str(PORT)],
        cwd=DASHBOARD,
    )


if __name__ == "__main__":
    sys.exit(main())
