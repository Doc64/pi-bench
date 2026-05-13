#!/usr/bin/env python3
"""
lhm_probe.py -- One-off diagnostic for the LibreHardwareMonitor JSON endpoint.

Connects to LHM's web server (default http://localhost:8085/data.json), walks
the sensor tree, and prints all sensors of "interesting" types: temperatures,
power, fans, clocks, load, voltage, control (PWM). Used to verify what's
exposed on a given machine before integrating LHM into the main benchmark.

Make sure LHM is running and Options -> Remote Web Server -> Run is checked.

Usage:
    python lhm_probe.py
    python lhm_probe.py --url http://localhost:8085/data.json
"""

import argparse
import json
import sys
import urllib.request


# Sensor types worth looking at for a CPU/cooling benchmark
INTERESTING_TYPES = {
    "Temperature", "Power", "Fan", "Clock", "Load", "Voltage", "Control",
}


def fetch_json(url, timeout=5):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.load(resp)


def walk(node, path, out):
    """Recursively collect every sensor leaf whose Type is in INTERESTING_TYPES."""
    text = node.get("Text", "") or ""
    new_path = path + [text] if text else path
    typ = node.get("Type")
    if typ and typ in INTERESTING_TYPES:
        out.append({
            "path": " / ".join(new_path),
            "type": typ,
            "value": node.get("Value", "") or "",
            "min":   node.get("Min", "")   or "",
            "max":   node.get("Max", "")   or "",
            "sensor_id": node.get("SensorId", "") or "",
        })
    for child in node.get("Children", []) or []:
        walk(child, new_path, out)


def main():
    ap = argparse.ArgumentParser(description="LibreHardwareMonitor JSON probe")
    ap.add_argument("--url", default="http://localhost:8085/data.json",
                    help="LHM web-server JSON endpoint")
    args = ap.parse_args()

    print("Probing LHM at {} ...\n".format(args.url))
    try:
        data = fetch_json(args.url)
    except Exception as e:
        print("ERROR: could not fetch JSON: {}".format(e))
        print("  - Is LHM running?")
        print("  - Is Options -> Remote Web Server -> Run checked?")
        print("  - Is the bind interface 0.0.0.0 (or 127.0.0.1)?")
        sys.exit(1)

    sensors = []
    walk(data, [], sensors)

    if not sensors:
        print("WARNING: server reachable but no sensors of interesting types found.")
        sys.exit(0)

    by_type = {}
    for s in sensors:
        by_type.setdefault(s["type"], []).append(s)

    print("Found {} sensors across {} types.\n".format(len(sensors), len(by_type)))
    for typ in sorted(by_type.keys()):
        print("=" * 78)
        print("{}  ({} sensors)".format(typ, len(by_type[typ])))
        print("=" * 78)
        for s in by_type[typ]:
            shown_path = s["path"]
            if len(shown_path) > 60:
                shown_path = "..." + shown_path[-57:]
            print("  {:<60s}  now={:<12s} max={:<12s}".format(
                shown_path, s["value"], s["max"]))
            if s["sensor_id"]:
                print("    id: {}".format(s["sensor_id"]))
        print()


if __name__ == "__main__":
    main()
