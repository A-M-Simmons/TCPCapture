#!/usr/bin/env python3
"""
tcpdump_service.py

Service that runs tcpdump on multiple interfaces,
rotating every N MB and keeping a limited number of files.

Configuration is loaded from /etc/tcpdump_service.conf
"""

import subprocess
import signal
import sys
import time
from pathlib import Path
import configparser

CONFIG_FILE = "/etc/tcpdump_service.conf"

# Load configuration
config = configparser.ConfigParser()
read_files = config.read(CONFIG_FILE)
if not read_files:
    print(f"Error: could not read config file {CONFIG_FILE}", file=sys.stderr)
    sys.exit(1)

settings = config["settings"]

INTERFACES = [i.strip() for i in settings.get("interfaces", "").split(",") if i.strip()]
OUTPUT_DIR = Path(settings.get("output_dir", "/var/log/tcpdump"))
TCPDUMP_BIN = settings.get("tcpdump_bin", "/usr/bin/tcpdump")
ROTATE_SIZE_MB = settings.getint("rotate_size_mb", 100)
MAX_ROTATED_FILES = settings.getint("max_rotated_files", 20)
EXTRA_ARGS = [arg.strip() for arg in settings.get("extra_args", "").split(",") if arg.strip()]

# Ensure output dir exists
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

processes = {}


def build_cmd(interface: str, out_base: Path):
    """Build tcpdump command for an interface with size-rotation."""
    outfile = str(out_base / f"{interface}.pcap")
    cmd = [
        TCPDUMP_BIN,
        "-i", interface,
        "-s", "0",                   # capture full packet (layer 2 + payload)
        "-w", outfile,
        "-C", str(ROTATE_SIZE_MB),   # rotate size
        "-W", str(MAX_ROTATED_FILES) # keep max files
    ]
    cmd += EXTRA_ARGS
    return cmd


def start_all():
    for iface in INTERFACES:
        cmd = build_cmd(iface, OUTPUT_DIR)
        stderr_path = OUTPUT_DIR / f"{iface}.stderr.log"
        f_err = open(stderr_path, "ab")
        p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=f_err)
        processes[iface] = (p, f_err)
        print(f"Started tcpdump for {iface} (pid {p.pid}), writing to {OUTPUT_DIR}/{iface}.pcap*")


def stop_all():
    for iface, (p, f_err) in processes.items():
        try:
            print(f"Stopping tcpdump for {iface} (pid {p.pid})")
            p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=5)
        except Exception as e:
            print(f"Error stopping {iface}: {e}")
        finally:
            try:
                f_err.close()
            except Exception:
                pass
    processes.clear()


def handle_sig(signum, frame):
    print(f"Received signal {signum}, shutting down...")
    stop_all()
    sys.exit(0)


def main():
    signal.signal(signal.SIGTERM, handle_sig)
    signal.signal(signal.SIGINT, handle_sig)

    if not Path(TCPDUMP_BIN).exists():
        print(f"tcpdump binary not found at {TCPDUMP_BIN}", file=sys.stderr)
        sys.exit(2)

    if not OUTPUT_DIR.exists():
        try:
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"Failed to create output dir {OUTPUT_DIR}: {e}", file=sys.stderr)
            sys.exit(2)

    start_all()

    try:
        while True:
            for iface, (p, f_err) in list(processes.items()):
                ret = p.poll()
                if ret is not None:
                    print(f"tcpdump for {iface} exited with code {ret}; restarting in 2s...")
                    try:
                        f_err.close()
                    except Exception:
                        pass
                    time.sleep(2)
                    cmd = build_cmd(iface, OUTPUT_DIR)
                    f_err = open(OUTPUT_DIR / f"{iface}.stderr.log", "ab")
                    newp = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=f_err)
                    processes[iface] = (newp, f_err)
                    print(f"Restarted tcpdump for {iface} (pid {newp.pid})")
            time.sleep(1)
    except KeyboardInterrupt:
        handle_sig(signal.SIGINT, None)


if __name__ == "__main__":
    main()
