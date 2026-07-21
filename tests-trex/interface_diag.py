import asyncio
import asyncssh
import subprocess
import json
import re
import sys
import time

class InterfaceDiagnostics:
    def __init__(self, hosts=None, host_map=None):
        self.hosts = hosts if hosts is not None else {
             'sunset': ['redwest', 'redeast'],
             'west': ['red', 'black'],
             'east': ['red', 'black']
        }
        self.host_map = host_map if host_map is not None else {
             'sunset': {'HostName': 'localhost', 'User': None},
             'west': {'HostName': 'westa', 'User': 'root'},
             'east': {'HostName': 'easta', 'User': 'root'},
        }
        self.commands = [
            (
                lambda iface: f"ethtool --json --include-statistics -a {iface}",
                self.parse_ethtool_stats
            ),
            (
                lambda iface: f"ip -j -s link show dev {iface}",
                self.parse_ip_stats
            )
        ]
        self.stats_start = {}  # host -> iface -> stats
        self.stats_end = {}    # host -> iface -> stats
        self.stats_diff = {}   # host -> iface -> diff
        self.errors = []       # list of {host, interface, command, error}
        self._seen_errors = set()
        self.verbose = True

    def parse_ethtool_stats(self, output):
        return json.loads(output)[0]

    def parse_ip_stats(self, output):
        return json.loads(output)[0]

    def set_stats(self, container, host, iface, stats):
        if host not in container:
            container[host] = {}
        container[host][iface] = stats

    def remove_empty_lists(self, d):
      if isinstance(d, dict):
        # Recursively process dictionary
        return {k: self.remove_empty_lists(v) for k, v in d.items() if v != []}
      elif isinstance(d, list):
        # Optionally, process list elements too (if lists of dicts)
        return [self.remove_empty_lists(x) for x in d if x != {} and x != []]
      else:
        return d

    def compute_stats_diff(self):
        stats_start = self.stats_start
        stats_end = self.stats_end
        stats_diff = {}
        for device in stats_start:
            stats_diff[device] = {}
            for iface in stats_start[device]:
                stats_diff[device][iface] = []
                # Build index for stats_end entries by ifname (or other unique field)
                end_entries = stats_end[device][iface]
                end_lookup = {}
                for e in end_entries:
                    # Choose unique field(s), here 'ifname' and 'ifindex'
                    key = (e.get("ifname"), e.get("ifindex"))
                    end_lookup[key] = e
                # Compare by key rather than position
                for entry_start in stats_start[device][iface]:
                    key = (entry_start.get("ifname"), entry_start.get("ifindex"))
                    entry_end = end_lookup.get(key)
                    if not entry_end:
                        continue  # No match found
                    entry_diff = {}
                    # ... (diff logic for statistics as in previous answer)
                    # Only include fields with nonzero difference
                    # (Insert previous statistical diff code here)
                    if "statistics" in entry_start and "statistics" in entry_end:
                        for stat in ["tx_pause_frames", "rx_pause_frames"]:
                            diff = entry_end["statistics"].get(stat, 0) - entry_start["statistics"].get(stat, 0)
                            if diff != 0:
                                if "statistics" not in entry_diff:
                                    entry_diff["statistics"] = {}
                                entry_diff["statistics"][stat] = diff
                    for sub in ["rx", "tx"]:
                        if "stats64" in entry_start and "stats64" in entry_end:
                            for fld in ["errors", "missed", "dropped"]:
                                diff = entry_end["stats64"][sub].get(fld, 0) - entry_start["stats64"][sub].get(fld, 0)
                                if diff != 0:
                                    entry_diff.setdefault("stats64", {}).setdefault(sub, {})[fld] = diff
                    if entry_diff:
                        stats_diff[device][iface].append(entry_diff)

        self.stats_diff = self.remove_empty_lists(stats_diff)
        return self.stats_diff


    async def run_local(self, command):
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        return {
            'stdout': stdout.decode(),
            'stderr': stderr.decode(),
            'exit_status': proc.returncode,
            'error': None if proc.returncode == 0 else stderr.decode()
        }

    async def run_ssh(self, HostName, User, command):
        try:
            async with asyncssh.connect(HostName, username=User) as conn:
                result = await conn.run(command, check=False)
            return {
                'stdout': result.stdout,
                'stderr': result.stderr,
                'exit_status': result.exit_status,
                'error': None if result.exit_status == 0 else result.stderr
            }
        except Exception as e:
            return {
                'stdout': '',
                'stderr': str(e),
                'exit_status': -1,
                'error': str(e)
            }

    async def collect_data(self, phase="start"):
        tasks = []
        results = []
        parsers = []
        for host, interfaces in self.hosts.items():
            HostName = self.host_map[host]['HostName']
            User = self.host_map[host]['User']
            ssh_cmd = None
            for iface in interfaces:
                for cmdfunc, parse_func in self.commands:
                    cmd = cmdfunc(iface)
                    if HostName == 'localhost':
                        task = self.run_local(cmd)
                    else:
                        task = self.run_ssh(HostName, User, cmd)
                        ssh_cmd = f"ssh {User}@{HostName} '{cmd}'"
                    tasks.append(asyncio.create_task(task))
                    results.append({
                        'host': host,
                        'interface': iface,
                        'command': cmd if HostName == 'localhost' else ssh_cmd,
                        'phase': phase
                    })
                    parsers.append(parse_func)

        raw_results = await asyncio.gather(*tasks)
        collect_results = []
        for meta, result, parse_func in zip(results, raw_results, parsers):
            entry = {**meta, **result}
            if entry['error'] or entry['exit_status'] != 0:
                err = {
                    "host": entry['host'],
                    "interface": entry['interface'],
                    "command": entry['command'],
                    "ok": False,
                    "error": entry['error'],
                }
                err_key = (entry['host'], entry['interface'], entry['command'])
                if err_key not in self._seen_errors:
                    self._seen_errors.add(err_key)
                    self.errors.append(err)
                    print(f"Warning: {entry['host']}:{entry['interface']} "
                          f"`{entry['command']}` failed: {entry['error']}")
                collect_results.append(err)
                continue

            stats = parse_func(entry["stdout"])
            entry["stats"] = stats

            if entry['phase'] == "start":
                d = self.stats_start
            elif entry['phase'] == "end":
                d = self.stats_end
            else:
                d = self.stats_start

            if entry['host'] not in d:
                d[entry['host']] = {}
            if entry['interface'] not in d[entry['host']]:
                d[entry['host']][entry['interface']] = []

            d[entry['host']][entry['interface']].append(stats)
            collect_results.append({
                "host": entry['host'],
                "interface": entry['interface'],
                "command": entry['command'],
                "ok": True,
            })

        return collect_results

    def export_stats_rooted(self):
        d = {
            "stats_start": self.stats_start,
            "stats_end": self.stats_end,
            "stats_diff": self.stats_diff,
        }
        if self.errors:
            d["errors"] = self.errors
        return d

# Usage Example:
async def main():
    diag = InterfaceDiagnostics()
    # print("Collecting start stats...")
    await diag.collect_data(phase="start")
    # print("\nCollecting end stats and computing differences...")
    await diag.collect_data(phase="end")
    print("\nAll stats:\n")
    print(diag.export_stats_rooted())

# if __name__ == "__main__":
#    asyncio.run(main())
