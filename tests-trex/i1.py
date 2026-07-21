#!/root/venv/bin/python3.12
import asyncio
import json
import sys
import os
import tomllib
from interface_diag import InterfaceDiagnostics

STATS_IFACES = {
    'sun': ['redwest', 'redeast'],
    'west': ['red', 'black'],
    'east': ['red', 'black'],
}

def load_stats_config(filepath):
    """Load [stats] section from TOML config file."""
    with open(filepath, "rb") as f:
        raw = tomllib.load(f)
    return raw.get("stats", {})

async def main():
    # Load host config from u1.conf (or path given as argv[1])
    conf_path = sys.argv[1] if len(sys.argv) > 1 else "u1.conf"
    if not os.path.exists(conf_path):
        print(f"Error: config file '{conf_path}' not found", file=sys.stderr)
        sys.exit(1)

    stats_conf = load_stats_config(conf_path)
    if not stats_conf:
        print(f"Error: no [stats] section in {conf_path}", file=sys.stderr)
        sys.exit(1)

    host_map = {}
    for name, cfg in stats_conf.items():
        host_map[name] = {
            'HostName': cfg.get('host', name),
            'User': cfg.get('user'),
        }
    hosts = {name: STATS_IFACES.get(name, []) for name in host_map}

    diag = InterfaceDiagnostics(hosts=hosts, host_map=host_map)
    results = await diag.collect_data(phase="start")

    # Report errors
    errors = [r for r in results if not r["ok"]]
    if errors:
        for r in errors:
            print(f"Warning: {r['host']}:{r['interface']} {r.get('error')}", file=sys.stderr)

    print(json.dumps(diag.export_stats_rooted(), indent=2))

if __name__ == "__main__":
    asyncio.run(main())
