#!/root/venv/bin/python3.9
import json
import sys
from interface_diag import InterfaceDiagnostics

if __name__ == "__main__":
    with open("t1.json", "r") as f:
        data = json.load(f)

    # Extract from stats key
    stats_start = data["stats"]["stats_start"]
    stats_end = data["stats"]["stats_end"]

    diag = InterfaceDiagnostics(hosts=[])
    diag.stats_start = stats_start
    diag.stats_end = stats_end

    diff = diag.compute_stats_diff()
    print(json.dumps(diff, indent=2))

