#!/root/venv/bin/python3.12
import sys
import os
import json
import csv
import time
import ipaddress
import asyncio
import tomllib
import subprocess
from interface_diag import InterfaceDiagnostics

# Hardcoded interface map (which interfaces to check per stats host)
STATS_IFACES = {
    'sun': ['redwest', 'redeast'],
    'west': ['red', 'black'],
    'east': ['red', 'black'],
}

sys.path.append('/var/tmp/trex-v3.08/automation/trex_control_plane/interactive')
sys.path.append('/var/tmp/trex-v3.08/scripts')
sys.path.append('/var/tmp/trex-v3.08/automation/trex_control_plane/interactive/trex_stl_lib')

from types import SimpleNamespace

import argparse
from trex.stl.api import (
    STLClient, STLStream, STLTXCont, STLPktBuilder, STLTXSingleBurst,
    STLScVmRaw, STLVmFlowVar, STLVmWrFlowVar, STLVmFixIpv4, STLVmFixChecksumHw
)
from trex.common.trex_exceptions import TRexError
from scapy.all import Ether, IP, IPv6, UDP

def trex_connect(server):
    c = STLClient(server=server)
    try:
        c.connect()
    except TRexError:
        print(f"Error: cannot connect to TRex server at {server}. Is it running?")
        sys.exit(1)
    return c

def is_ipv4_address(ip):
    try:
        return isinstance(ipaddress.ip_address(ip), ipaddress.IPv4Address)
    except ValueError:
        return False

def is_ipv6_address(ip):
    try:
        return isinstance(ipaddress.ip_address(ip), ipaddress.IPv6Address)
    except ValueError:
        return False

def int_mac_low(macstr):
    # Returns integer value of lower 4 bytes
    return int(macstr.replace(":", "")[-8:], 16)


def create_pkt_udp_with_vm(src_mac, dst_mac, start_ip, src_ip_count, dst_ip, dst_ip_count, frame_size,
                       src_port, src_port_count, dst_port, dst_port_count, l4_proto="UDP"):
    '''
    Create a UDP packet with Scapy and TRex VM instructions to vary fields.
    Supports source and destination IP and port ranges.
    When src ip changes the src mac changes too.
    '''

    ip_ver = ipaddress.ip_address(start_ip).version
    min_mac_low = int_mac_low(src_mac)
    max_mac_low = min_mac_low + src_ip_count - 1
    l4_offset = 34 if ip_ver == 4 else 54
    l3_offset = 14  # Ethernet header size
    UDP_PROTO = 17  # UDP protocol number

    vm_instr = [
       STLVmFlowVar(name="src_mac_low", min_value=min_mac_low, max_value=max_mac_low, size=4, op="inc"),
       STLVmWrFlowVar(fv_name="src_mac_low", pkt_offset=8), # 8 because src MAC 6 + 2. increment lower 4 bytes

       STLVmFlowVar(name="src_port", min_value=src_port, max_value=src_port + src_port_count - 1, size=2, op="inc"),
       STLVmWrFlowVar(fv_name="src_port", pkt_offset="UDP.sport"),

       STLVmFlowVar(name="dst_port", min_value=dst_port, max_value=dst_port + dst_port_count - 1, size=2, op="inc"),
       STLVmWrFlowVar(fv_name="dst_port", pkt_offset="UDP.dport"),
       STLVmFixChecksumHw(l3_offset = l3_offset, l4_offset=l4_offset, l4_type=UDP_PROTO)

       ]

    if ip_ver == 4:
        vm_instr += [
            STLVmFlowVar(name="src_ipv4", min_value=int(ipaddress.IPv4Address(start_ip)),
                         max_value=int(ipaddress.IPv4Address(start_ip)) + src_ip_count - 1, size=4, op="inc"),
            STLVmWrFlowVar(fv_name="src_ipv4", pkt_offset="IP.src"),
            STLVmFlowVar(name="dst_ipv4", min_value=int(ipaddress.IPv4Address(dst_ip)),
                         max_value=int(ipaddress.IPv4Address(dst_ip)) + dst_ip_count - 1, size=4, op="inc"),
            STLVmWrFlowVar(fv_name="dst_ipv4", pkt_offset="IP.dst"),
            STLVmFixIpv4(offset="IP")
        ]
    else:
        vm_instr += [
            STLVmFlowVar(name="src_ipv6", min_value=int(ipaddress.IPv6Address(start_ip)),
                         max_value=int(ipaddress.IPv6Address(start_ip)) + src_ip_count - 1, size=16, op="inc"),
            STLVmWrFlowVar(fv_name="src_ipv6", pkt_offset="IPv6.src"),
            STLVmFlowVar(name="dst_ipv6", min_value=int(ipaddress.IPv6Address(dst_ip)),
                         max_value=int(ipaddress.IPv6Address(dst_ip)) + dst_ip_count - 1, size=16, op="inc"),
            STLVmWrFlowVar(fv_name="dst_ipv6", pkt_offset="IPv6.dst"),
        ]

    # this is the base packet, Scapy will build it and change fields via VM in STLPktBuilder.
    base_pkt = Ether(src=src_mac, dst=dst_mac) / (
                IP(src=start_ip, dst=dst_ip) if ip_ver == 4 else IPv6(src=start_ip, dst=dst_ip)
                ) / UDP(dport=dst_port, sport=src_port)

    vm = STLScVmRaw(vm_instr)
    pkt_len = len(base_pkt)
    pad = b'\0' * (frame_size - pkt_len) if pkt_len < frame_size else b''

    pkt = STLPktBuilder(pkt=base_pkt/pad, vm=vm)
    return pkt


def create_pkt_udp(src_mac, dst_mac, src_ip, dst_ip, frame_size, src_port, dst_port):

    if is_ipv6_address(src_ip) or is_ipv6_address(dst_ip):
        ip_layer = IPv6(src=src_ip, dst=dst_ip)
    elif is_ipv4_address(src_ip) or is_ipv4_address(dst_ip):
        ip_layer = IP(src=src_ip, dst=dst_ip)
    else:
        raise ValueError("Invalid IP address format")

    pkt_base = Ether(src=src_mac, dst=dst_mac)/ip_layer/UDP(dport=dst_port, sport=src_port)
    pkt_len = len(pkt_base)
    pad = b'\0' * (frame_size - pkt_len) if pkt_len < frame_size else b''

    return STLPktBuilder(pkt=pkt_base/pad)

def bits_to_gibps(bits_per_sec):
    return bits_per_sec / (1024**3)  # bits to GiB/sec

def run_priming(args, st, n=1, delay_ms=100):
    """
    Priming run to establish SA and avoid initial packet loss.
    Sends streams one by one.
    The first stream is sent twice.
    Delay (in milliseconds) between streams.
    """
    c = trex_connect(args.server)
    try:
        c.reset(ports=[0, 1])
        c.clear_stats()

        use_fwd = not args.rev  # forward unless --rev only
        use_rev = args.use_rev
        ports = []
        if use_fwd:
            ports.append(0)
        if use_rev:
            ports.append(1)

        for flow_id in range(st.flows):
            src_port = args.src_port + flow_id

            if use_fwd:
                # Forward: port 0 → port 1
                fwd_pkt = create_pkt_udp(args.src_mac, args.dst_mac, args.src_ip,
                                 args.dst_ip, st.frame_size, src_port,
                                 args.dst_port)
                fwd_stream = STLStream(packet=fwd_pkt, mode=STLTXSingleBurst(total_pkts=n))
                c.add_streams([fwd_stream], ports=[0])

            if use_rev:
                # Reverse: port 1 → port 0
                rev_pkt = create_pkt_udp(args.rev_src_mac, args.rev_dst_mac, args.rev_src_ip,
                                 args.rev_dst_ip, st.frame_size, src_port, args.dst_port)

                rev_stream = STLStream(packet=rev_pkt, mode=STLTXSingleBurst(total_pkts=n))
                c.add_streams([rev_stream], ports=[1])

            # Send first stream twice, others once; Jacob Two Two to get Fallback SA and per cpu SA
            send_times = 2 if flow_id == 0 else 1

            for i in range(send_times):
                c.start(ports=ports, mult="1")
                c.wait_on_traffic(ports=ports)
                time.sleep(delay_ms / 1000.0)

            c.reset(ports=[0, 1])
            time.sleep(delay_ms / 1000.0)

    finally:
        c.disconnect()

def wait_for_priming(args, st):
    """Wait for priming packets to arrive at rx ports, then clear stats.
    Returns priming stats dict. Max wait: 1s poll + 1s extra if nothing arrived."""
    c = trex_connect(args.server)
    try:
        use_fwd = not args.rev
        use_rev = args.use_rev

        # Count expected priming packets per direction:
        # run_priming called twice, first flow sent 2x, rest 1x each
        pkts_per_call = st.flows + 1  # +1 for the first flow's extra send
        expected = pkts_per_call * 2  # two run_priming calls

        # Poll for up to 1 second (10 x 100ms)
        arrived = False
        for _ in range(10):
            stats = c.get_stats(ports=[0, 1])
            rx_fwd = stats[1].get("ipackets", 0) if use_fwd else expected
            rx_rev = stats[0].get("ipackets", 0) if use_rev else expected
            if rx_fwd >= expected and rx_rev >= expected:
                arrived = True
                break
            time.sleep(0.1)

        if not arrived:
            # Wait another second for stragglers
            time.sleep(1.0)
            stats = c.get_stats(ports=[0, 1])

        # Capture priming stats before clearing
        p0 = stats[0]
        p1 = stats[1]
        priming_stats = {}
        if use_fwd:
            tx = p0.get("opackets", 0)
            rx = p1.get("ipackets", 0)
            priming_stats["priming_fwd_tx"] = tx
            priming_stats["priming_fwd_rx"] = rx
            priming_stats["priming_fwd_loss"] = tx - rx
        if use_rev:
            tx = p1.get("opackets", 0)
            rx = p0.get("ipackets", 0)
            priming_stats["priming_rev_tx"] = tx
            priming_stats["priming_rev_rx"] = rx
            priming_stats["priming_rev_loss"] = tx - rx

        priming_stats["priming_arrived"] = arrived

        lost = sum(v for k, v in priming_stats.items() if k.endswith("_loss"))
        status = "ok" if arrived and lost == 0 else f"wait={'ok' if arrived else 'timeout'} loss={lost}"
        print(f" priming: {status}", end="")

        # Clear stats so test starts clean
        c.clear_stats()
    finally:
        c.disconnect()

    return priming_stats

def run_priming_delay(args, st):
    run_priming(args, st, n=1, delay_ms=100)
    run_priming(args, st, n=1, delay_ms=100)
    return wait_for_priming(args, st)

def run_test(args, st):
    c = trex_connect(args.server)
    try:
        c.reset(ports=[0, 1])
        c.clear_stats()

        use_fwd = not args.rev  # forward unless --rev only
        use_rev = args.use_rev
        ports = []
        if use_fwd:
            ports.append(0)
        if use_rev:
            ports.append(1)

        fwd_streams = []
        rev_streams = []

        for flow_id in range(st.flows):
            src_port = args.src_port + flow_id

            if use_fwd:
                # Forward: port 0 → port 1
                fwd_pkt = create_pkt_udp_with_vm(args.src_mac, args.dst_mac,
                           args.src_ip, args.src_ips,
                           args.dst_ip, args.dst_ips, st.frame_size, src_port, args.src_ports,
                           args.dst_port, args.dst_ports)
                fwd_streams.append(STLStream(packet=fwd_pkt, mode=STLTXCont(pps=st.pps)))

            if use_rev:
                # Reverse: port 1 → port 0
                rev_pkt = create_pkt_udp_with_vm(args.rev_src_mac, args.rev_dst_mac,
                           args.rev_src_ip, args.dst_ips,
                           args.rev_dst_ip, args.src_ips, st.frame_size, args.dst_port, args.dst_ports,
                           src_port, args.src_ports)
                rev_streams.append(STLStream(packet=rev_pkt, mode=STLTXCont(pps=st.pps)))

        if use_fwd:
            c.add_streams(fwd_streams, ports=[0])
        if use_rev:
            c.add_streams(rev_streams, ports=[1])
        start_time = time.time()  # Record start

        c.start(ports=ports, mult="1", duration=args.duration)
        c.wait_on_traffic(ports=ports)
        end_time = time.time()  # Record end
        elapsed = end_time - start_time
        deviation = elapsed - args.duration

        if abs(deviation) > 0.2:
            runtime_deviation = deviation
        else:
            runtime_deviation = 0   # or "within tolerance"

        stats_ports = c.get_stats(ports=[0, 1])
        p0 = stats_ports[0]
        p1 = stats_ports[1]

        result = {}

        if use_fwd:
            fwd_tx_pkts = p0.get("opackets", 0)
            fwd_rx_pkts = p1.get("ipackets", 0)
            result.update({
                "fwd_tx_pps": p0.get("tx_pps", 0),
                "fwd_tx_bps": p0.get("tx_bps", 0),
                "fwd_tx_throughput_gibps": bits_to_gibps(p0.get("tx_bps_L1", 0)),
                "fwd_tx_errors": p0.get("tx_err", 0),
                "fwd_tx_opackets": fwd_tx_pkts,
                "fwd_tx_obytes": p0.get("obytes", 0),
                "fwd_rx_pps": p1.get("rx_pps", 0),
                "fwd_rx_bps": p1.get("rx_bps", 0),
                "fwd_rx_throughput_gibps": bits_to_gibps(p1.get("rx_bps_L1", 0)),
                "fwd_rx_ipackets": fwd_rx_pkts,
                "fwd_rx_ibytes": p1.get("ibytes", 0),
                "fwd_l_pkts": fwd_tx_pkts - fwd_rx_pkts,
                "fwd_l_pkts_percent": ((fwd_tx_pkts - fwd_rx_pkts) / fwd_tx_pkts * 100) if fwd_tx_pkts else 0,
            })

        if use_rev:
            rev_tx_pkts = p1.get("opackets", 0)
            rev_rx_pkts = p0.get("ipackets", 0)
            result.update({
                "rev_tx_pps": p1.get("tx_pps", 0),
                "rev_tx_bps": p1.get("tx_bps", 0),
                "rev_tx_throughput_gibps": bits_to_gibps(p1.get("tx_bps_L1", 0)),
                "rev_tx_errors": p1.get("tx_err", 0),
                "rev_tx_opackets": rev_tx_pkts,
                "rev_tx_obytes": p1.get("obytes", 0),
                "rev_rx_pps": p0.get("rx_pps", 0),
                "rev_rx_bps": p0.get("rx_bps", 0),
                "rev_rx_throughput_gibps": bits_to_gibps(p0.get("rx_bps_L1", 0)),
                "rev_rx_ipackets": rev_rx_pkts,
                "rev_rx_ibytes": p0.get("ibytes", 0),
                "rev_l_pkts": rev_tx_pkts - rev_rx_pkts,
                "rev_l_pkts_percent": ((rev_tx_pkts - rev_rx_pkts) / rev_tx_pkts * 100) if rev_tx_pkts else 0,
            })

        result.update({
            "direction": "bidir" if args.bidir else ("rev" if args.rev else "fwd"),
            "src_ips": args.src_ips,
            "dst_ips": args.dst_ips,
            "src_ports": args.src_ports,
            "dst_ports": args.dst_ports,
            "elapsed_runtime": elapsed,
            "duration": args.duration,
            "runtime_deviation": runtime_deviation
        })

        stats = c.get_stats(ports=[0, 1])
        global_stats = stats.get('global', {})
        cpu_usage = global_stats.get('cpu_util', None)

        if cpu_usage is not None:
            num_cpus = os.cpu_count()  # system cores count, for reference only

            # 'cpu_usage' is already a total/average CPU usage (percentage)
            avg_load = cpu_usage

            # print(f"Average CPU use per core (overall): {avg_load:.2f}% Number of CPUs on system: {num_cpus}")

            result.update({
                "cpu_load_total": cpu_usage,
                "cpu_load_avg": avg_load,
                "num_cpus": num_cpus
            })
        parts = []
        if use_fwd:
            parts.append(f"fwd rx {result['fwd_rx_throughput_gibps']:.2f} Gbps loss {result['fwd_l_pkts_percent']:.2f}%")
        if use_rev:
            parts.append(f"rev rx {result['rev_rx_throughput_gibps']:.2f} Gbps loss {result['rev_l_pkts_percent']:.2f}%")
        parts.append(f"{elapsed:.2f} sec")
        print(" | ".join(parts))
    finally:
        c.disconnect()

    return result

async def run_tests (args, st, diag=None):
    all_runs_results = []  # To hold dicts per run

    # Collect start stats
    if diag:
        try:
            await diag.collect_data(phase="start")
        except Exception as e:
            print(f"Warning: stats start collection failed: {e}")

    # Run all test runs and collect results
    for run_id in range(1, args.runs + 1):
        print(f" run {run_id}/{args.runs} ",  end="")
        priming_stats = {}
        if args.priming:
            priming_stats = run_priming_delay(args, st)
        run_result = run_test(args, st)
        run_result.update(priming_stats)
        run_result.update({
            "frame_size": st.frame_size,
            "tx_pps_req": st.pps_req,
            "tx_pps_per_flow": st.pps,
            "tx_flow_throughput": args.throughput,
            "flows":  st.flows,
            "flows_start": args.flows_start,
            "flows_end": args.flows_end,
            "run": run_id,
            "runs": args.runs,
            })
        all_runs_results.append(run_result)

    # Collect end stats and compute diff
    if diag:
        try:
            await diag.collect_data(phase="end")
            diag.compute_stats_diff()
        except Exception as e:
            print(f"Warning: stats end collection failed: {e}")

    return all_runs_results

def compute_pps(args, frame_size):
    """
    Compute Ethernet PPS from throughput (bps) and IP packet size (bytes).
    This accounts for
    Ethernet Frame is IP packet + Ethernet overhead
    Ethernet header: header 14 bytes: (6 bytes destination MAC + 6 bytes source MAC + 2 bytes EtherType)

    Ethernet Overhead
        # Frame Check Sequence (FCS) 4 bytes: bytes CRC at the end

        preamble 7 bytes
        Start Frame Delimiter (SFD) 1 Byte
        Inter-frame gap (IFG): 12 bytes — a gap time between frames, treated as overhead on the wire
        = 20 bytes total.

    https://www.intel.com/content/www/us/en/docs/programmable/683338/22-1/performance-and-fmax-requirements-for.html
    Args:
        args: object with attribute 'throughput', throughput string parsed by parse_rate_value()
        frame_size: int, IP packet payload size in bytes (e.g., 1500 for full MTU)

    Returns:
        int: Packets per second (PPS) that fit in the given throughput with Ethernet overhead considered.
    """

    bps = parse_rate_value(args.throughput, "throughput")

    ethernet_overhead_bytes = 20
    frame_size_total = frame_size + ethernet_overhead_bytes

    bits_per_packet = frame_size_total * 8

    pps = int(bps / bits_per_packet)

    return pps

def parse_rate_value(s, option):
    """
    Parse a rate string with optional binary unit suffix into an integer value.
    K = 1 x 10^3, M = 1 x 10^6, G = 1 x 10^9

Assumptions:
    Link rate = 100 Gbps = 100,000,000,000 bits per second (decimal standard)

    Ethernet + physical overhead = 38 bytes total
    (Ethernet header 14 + FCS 4 + Preamble + SFD 8 + Inter-frame gap (IFG) 12)
    PPS calculated by dividing link rate by total bits per packet
    (IP packet size + 38 overhead bytes) × 8 (bits/byte)

    """

    if s is None:
        return 0

    s = s.strip().upper()

    try:
        if s.endswith('G'):
            num = float(s[:-1])
            return int(num * (10**9))
        elif s.endswith('M'):
            num = float(s[:-1])
            return int(num * (10**6))
        elif s.endswith('K'):
            num = float(s[:-1])
            return int(num * (10**3))
        else:
            # Assume raw integer rate (bps or pps)
            return int(s)
    except ValueError:
        raise ValueError(
            f"Invalid {option} value: '{s}'. "
            "Must be a number with optional G/M/K suffix."
        )

def iter_frame_pps(args):
    """Yield (frame_size, pps, label) for every frame-size × rate combination."""
    frame_sizes = args.frame_sizes if args.frame_sizes else Def.frame_sizes
    for frame_size in frame_sizes:
        if args.throughput:
            yield frame_size, compute_pps(args, frame_size), args.throughput
        else:
            for p in (args.pps if args.pps else Def.pps):
                yield frame_size, parse_rate_value(p, "pps"), p


def validate_test_plan(args):
    """Validate all test parameter combinations before starting any tests.
    Checks frame size minimums and L1 bandwidth against 100G line rate.
    Exits with error if any combination is invalid."""
    ip_ver = ipaddress.ip_address(args.src_ip).version
    if ip_ver == 4:
        min_frame = 42
        min_desc = "Ethernet(14) + IP(20) + UDP(8)"
    else:
        min_frame = 62
        min_desc = "Ethernet(14) + IPv6(40) + UDP(8)"

    line_rate_bps = 100 * 10**9  # 100G
    eth_overhead = 20  # preamble(7) + SFD(1) + IFG(12)
    directions = 2 if args.bidir else 1
    dir_note = " x2 (bidir)" if args.bidir else ""

    errors = []
    seen_frame_errors = set()

    for frame_size, pps, label in iter_frame_pps(args):
        if frame_size < min_frame:
            if frame_size not in seen_frame_errors:
                errors.append(
                    f"frame_size {frame_size} too small: "
                    f"minimum is {min_frame} bytes ({min_desc})"
                )
                seen_frame_errors.add(frame_size)
            continue

        l1_bps = pps * (frame_size + eth_overhead) * 8 * directions
        l1_gbps = l1_bps / 1e9
        if l1_bps > line_rate_bps:
            errors.append(
                f"frame_size {frame_size}, rate {label}: "
                f"L1 {l1_gbps:.2f} Gbps{dir_note} exceeds 100 Gbps line rate"
            )

    if errors:
        print("Validation failed:")
        for e in errors:
            print(f"  {e}")
        return False
    print("Validation OK")
    return True


def run_test_frame_sizes(args, diag=None):
    all_results_frame_size = []  # To hold dicts all frame sizes results
    for frame_size, pps, _ in iter_frame_pps(args):
        st = SimpleNamespace(pps=pps, pps_req = pps, frame_size=frame_size, flows=1, run=1)

        for flows in range(args.flows_start, args.flows_end + 1): # loop over flows
            st.flows = flows
            st.pps = pps/flows

            dir_str = " bidir" if args.bidir else (" rev" if args.rev else "")
            print(f"Setting flows {st.flows}/{args.flows_end} pps {st.pps:.2f}/{pps:.2f} per flow throughput {args.throughput} and frame-size {st.frame_size} runs {args.runs} duration {args.duration} sec{dir_str}")
            test_results = asyncio.run(run_tests(args, st, diag=diag))
            all_results_frame_size.extend(test_results)

            write_json(args.results_file, all_results_frame_size)

    return all_results_frame_size

def write_json(filename, all_results):
    with open(filename, 'w') as f:
        print(f"\nAll runs aggregated result as JSON: {filename}")
        json.dump(all_results, f, indent=2)

class Def:
  frame_sizes = [1440]
  pps = ["10K"]

class Def_v6:
  frame_sizes = [1440]
  pps = ["10K"]
  src_ip = "2001:db8:0:1::254"
  dst_ip = "2001:db8:0:2::254"

# MAC resolution: interface names and gateway IPs
IFACE_FWD = "redwest"    # local interface for forward src-mac
IFACE_REV = "redeast"    # local interface for reverse src-mac
GW_FWD = "192.0.1.254"   # gateway IP to ARP-resolve forward dst-mac
GW_REV = "192.0.2.254"   # gateway IP to ARP-resolve reverse dst-mac

def get_iface_mac(iface):
    """Read MAC address of a local network interface."""
    path = f"/sys/class/net/{iface}/address"
    try:
        with open(path) as f:
            return f.read().strip()
    except FileNotFoundError:
        print(f"Warning: interface {iface} not found, cannot resolve MAC")
        return None

def arp_resolve_mac(ip):
    """Ping IP to populate ARP cache, then read MAC from neighbor table."""
    subprocess.run(["ping", "-c", "1", "-W", "1", ip],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    result = subprocess.run(["ip", "neigh", "show", ip],
                            capture_output=True, text=True)
    for line in result.stdout.strip().split("\n"):
        parts = line.split()
        if "lladdr" in parts:
            return parts[parts.index("lladdr") + 1]
    print(f"Warning: cannot resolve MAC for {ip}")
    return None

def gen_config(filepath, args, parser, stats_config=None):
    """Write current options (defaults + CLI overrides) as a commented TOML file.
    Iterates parser argument groups automatically — adding a new arg to a group
    is all that's needed."""

    def fmt(val):
        if isinstance(val, bool):
            return "true" if val else "false"
        if isinstance(val, list):
            items = ", ".join(f'"{v}"' if isinstance(v, str) else str(v) for v in val)
            return f"[{items}]"
        if isinstance(val, str):
            return f'"{val}"'
        return str(val)

    skip = {"config", "gen_config", "help", "check_stats"}

    # Collect dests that belong to mutually exclusive groups
    mutex_dests = set()
    for mg in parser._mutually_exclusive_groups:
        for action in mg._group_actions:
            mutex_dests.add(action.dest)

    d = dict(vars(args))
    if not d.get("frame_sizes"):
        d["frame_sizes"] = Def.frame_sizes

    # Auto-resolve MACs that weren't explicitly set
    if d["src_mac"] is None:
        d["src_mac"] = get_iface_mac(IFACE_FWD)
    if d["rev_src_mac"] is None:
        d["rev_src_mac"] = get_iface_mac(IFACE_REV)
    if d["dst_mac"] is None:
        d["dst_mac"] = arp_resolve_mac(GW_FWD)
    if d["rev_dst_mac"] is None:
        d["rev_dst_mac"] = arp_resolve_mac(GW_REV)

    lines = ["# TRex test configuration\n\n"]

    for group in parser._action_groups:
        # Skip the two default groups (positional arguments, options)
        if group.title in ("positional arguments", "options"):
            continue

        actions = [a for a in group._group_actions if a.dest not in skip]
        if not actions:
            continue

        for title_line in group.title.split("\n"):
            lines.append(f"# {title_line}\n")

        for action in actions:
            key = action.dest.replace("_", "-")
            val = d.get(action.dest)

            # Comment out: None values and False members of mutually exclusive groups
            comment_out = (val is None) or (action.dest in mutex_dests and val is False)

            if comment_out:
                hint = f"  # {action.help}" if action.help else ""
                lines.append(f"# {key} = {fmt(val) if val is not None else '\"\"'}{hint}\n")
            else:
                lines.append(f"{key} = {fmt(val)}\n")

        lines.append("\n")

    # Write [stats] section
    if stats_config:
        lines.append("# Stats collection hosts\n")
        for name, cfg in stats_config.items():
            lines.append(f"[stats.{name}]\n")
            lines.append(f'host = "{cfg.get("host", name)}"\n')
            user = cfg.get("user")
            if user:
                lines.append(f'user = "{user}"\n')
            lines.append("\n")

    with open(filepath, "w") as f:
        f.writelines(lines)
    print(f"Config written to {filepath}")


def load_config(filepath, parser):
    """Load TOML config, validate keys.
    Returns (config_dict, stats_config) — caller merges with CLI args."""
    # Build set of valid dest names
    valid_dests = set()
    for action in parser._actions:
        if action.dest != "help":
            valid_dests.add(action.dest)

    with open(filepath, "rb") as f:
        raw_config = tomllib.load(f)

    # Validate keys and convert dashes to underscores
    config = {}
    stats_config = {}
    for key, val in raw_config.items():
        if key == "stats":
            stats_config = val
            continue
        dest_key = key.replace("-", "_")
        if dest_key not in valid_dests:
            print(f"Error: unknown config key '{key}' in {filepath}")
            sys.exit(1)
        config[dest_key] = val

    return config, stats_config


def merge_config(args, file_config, parser):
    """Merge file config into args. CLI values take priority over file values.
    For append args (--pps, --frame-sizes), CLI replaces file, not appends."""
    # Find the default value for each dest from the parser
    defaults = {}
    for action in parser._actions:
        defaults[action.dest] = action.default

    for key, file_val in file_config.items():
        cli_val = getattr(args, key, None)
        default_val = defaults.get(key)
        # If CLI value is the same as the parser default, user didn't set it
        if cli_val == default_val:
            setattr(args, key, file_val)


if __name__ == "__main__":

    d = Def()

    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, nargs="?", const="u1.conf", default=None,
                        metavar="FILE",
                        help="Load options from TOML config file (default: u1.conf)")
    parser.add_argument("--gen-config", type=str, nargs="?", const="u1.conf", default=None,
                        metavar="FILE",
                        help="Generate TOML config file from current options, then exit (default: u1.conf)")
    parser.add_argument("--validate", action="store_true", default=False,
                        help="Validate frame sizes and L1 bandwidth against 100G line rate, then exit")

    srv = parser.add_argument_group("TRex server")
    srv.add_argument("--server", type=str, default="127.0.0.1")

    fwd = parser.add_argument_group("Forward direction (port 0 → port 1)")
    fwd.add_argument("--src-mac", type=str, default=None)
    fwd.add_argument("--dst-mac", type=str, default=None)
    fwd.add_argument("--src-ip", type=str, default="192.0.1.1")
    fwd.add_argument("--dst-ip", type=str, default="192.0.2.250")
    fwd.add_argument("--src-ips", type=int, default=1)
    fwd.add_argument("--dst-ips", type=int, default=1)
    fwd.add_argument("--src-port", type=int, default=4501)
    fwd.add_argument("--dst-port", type=int, default=5201)
    fwd.add_argument("--src-ports", type=int, default=1)
    fwd.add_argument("--dst-ports", type=int, default=1)

    rev_grp = parser.add_argument_group("Reverse direction (port 1 → port 0)\nUsed with --bidir or --rev")
    rev_grp.add_argument('--rev-dst-mac', type=str, default=None,
                        help='DUT MAC on port 1 side')
    rev_grp.add_argument('--rev-src-mac', type=str, default=None,
                        help='default: TRex port 1 HW MAC')
    rev_grp.add_argument('--rev-src-ip', type=str, default=None,
                        help='default: dst-ip')
    rev_grp.add_argument('--rev-dst-ip', type=str, default="192.0.1.250")

    test = parser.add_argument_group("Test parameters")
    test.add_argument("--frame-sizes", type=int, action='append', default=[],
                        help="Specify frame size in bytes; can be used multiple times. Default is 1440 bytes L1 1518 - IPsec.")
    test.add_argument("--duration", type=int, default=30)
    test.add_argument("--runs", type=int, default=5)
    test.add_argument("--results-file", type=str, default="trex_results.json",
                        help="Results file name")
    test.add_argument('--priming', action=argparse.BooleanOptionalAction,
                        help='Enable/disable priming', default=True)
    test.add_argument('--stats', action=argparse.BooleanOptionalAction,
                        help='Enable/disable interface stats collection', default=True)
    test.add_argument('--check-stats', action='store_true', default=False,
                        help='Test stats collection (SSH + commands) and exit')

    dir_grp = parser.add_argument_group("Direction (mutually exclusive)")
    dir_mutex = dir_grp.add_mutually_exclusive_group()
    dir_mutex.add_argument('--bidir', action='store_true', default=False,
                        help='Enable bidirectional flows (forward + reverse)')
    dir_mutex.add_argument('--rev', action='store_true', default=False,
                        help='Reverse only (port 1 → port 0)')

    rate_grp = parser.add_argument_group("Rate (mutually exclusive)")
    rate_mutex = rate_grp.add_mutually_exclusive_group()
    rate_mutex.add_argument("--pps", type=str, action='append', default=None, help="Packets per second")
    rate_mutex.add_argument("--throughput", "--tp", type=str,
                       default=None,
                       help="Target throughput: G for Gbps, M for Mbps, e.g. 10G, 500M")

    flow_grp = parser.add_argument_group("Flow range")
    flow_grp.add_argument("--flows-start", "--flows", type=int, default=1, help="Number of UDP flows start")
    flow_grp.add_argument("--flows-end", type=int, default=1, help="Number of UDP flows end")

    args = parser.parse_args()

    # Load config file and merge — CLI values take priority
    file_config = {}
    stats_config = {}
    config_path = args.config
    if config_path:
        print(f"Using config: {config_path}")
    elif os.path.exists("u1.conf"):
        config_path = "u1.conf"
        print("Using config: u1.conf (auto-detected)")

    if config_path:
        file_config, stats_config = load_config(config_path, parser)
        merge_config(args, file_config, parser)

    if args.gen_config:
        gen_config(args.gen_config, args, parser, stats_config)
        sys.exit(0)

    # Build stats host_map and hosts from TOML [stats] config
    diag = None
    if args.stats and stats_config:
        host_map = {}
        for name, cfg in stats_config.items():
            host_map[name] = {
                'HostName': cfg.get('host', name),
                'User': cfg.get('user'),
            }
        hosts = {name: STATS_IFACES.get(name, []) for name in host_map}
        diag = InterfaceDiagnostics(hosts=hosts, host_map=host_map)

    if args.check_stats:
        if not diag:
            print("Error: no [stats] section in config file")
            sys.exit(1)
        results = asyncio.run(diag.collect_data(phase="check"))
        all_ok = True
        for r in results:
            status = "ok" if r["ok"] else f"FAIL: {r.get('error', 'unknown')}"
            print(f"  {r['host']}:{r['interface']} {r['command']} ... {status}")
            if not r["ok"]:
                all_ok = False
        sys.exit(0 if all_ok else 1)

    args.use_rev = args.bidir or args.rev
    if args.use_rev:
        if not args.rev_src_ip:
            args.rev_src_ip = args.dst_ip
        if not args.rev_dst_ip:
            args.rev_dst_ip = args.src_ip
        if not args.rev_src_mac:
            # Query TRex port 1 HW MAC as default
            c = trex_connect(args.server)
            try:
                info = c.get_port_info(ports=[1])[0]
                args.rev_src_mac = info['hw_mac']
                print(f"Using TRex port 1 HW MAC for reverse src: {args.rev_src_mac}")
            finally:
                c.disconnect()
        print(f"Reverse: {args.rev_src_ip} -> {args.rev_dst_ip} src-mac {args.rev_src_mac} dst-mac {args.rev_dst_mac}")

    _, ext = os.path.splitext(args.results_file)
    if ext.lower() != '.json':
        print(f"Warning: --output '{args.results_file}' does not have .json extension")

    all_results = []  # To hold dicts per run
    if args.flows_end <= args.flows_start:
        args.flows_end = args.flows_start

    if not args.frame_sizes :
        args.frame_sizes = d.frame_sizes

    if not args.throughput and not args.pps:
        args.pps = d.pps

    if args.validate:
        if not validate_test_plan(args):
            sys.exit(1)

    test_results = run_test_frame_sizes(args, diag=diag)
    all_results.extend(test_results)

    # Include stats in results if collected
    if diag and diag.stats_diff:
        final_output = {
            "results": all_results,
            "interface_stats": diag.export_stats_rooted(),
        }
    else:
        final_output = all_results

    write_json(args.results_file, final_output)
