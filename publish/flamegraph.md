Title: Generating Flame Graphs for XFRM Performance Analysis (Vienna, 23 Jul)
Date: 2026-07-23
Author: Antony Antony
Summary: How to use perf and FlameGraph to profile CPU cycles and cache misses for XFRM/IPsec code paths.

## Prerequisites

- [perf](https://perfwiki.github.io/main/tutorial/#sampling-with-perf-record)
- [FlameGraph](https://github.com/brendangregg/FlameGraph) Clone the github
- Likely a couple perl modules for FlameGraph.

### Installing perf

On Debian install [linux-perf](https://packages.debian.org/sid/linux-perf):
```
apt install linux-perf
```

On Fedora:
```
dnf install perf
```

Build locally from matching kernel source tree:
```
cd /path/to/your/linux-source
make -C tools/perf -j $(nproc)
make -C tools/perf install prefix=/usr/
```

or just Manual copy:
```
cp tools/perf/perf /usr/local/bin/perf
```

## Quick flame graph

Record cycles and L1 cache miss events on the CPU running xfrm code
(here CPU 5):

```
perf record -b -e cycles,L1-dcache-load-misses,L1-icache-load-misses:k -g -C 5 --call-graph dwarf
```

Generate the flame graph:

```
perf script > out.perf
cd FlameGraph
./stackcollapse-perf.pl ../out.perf > ../out.folded
./flamegraph.pl ../out.folded
```

The key option above is `-C 5`, which restricts the recording to a
single CPU. Run this on the CPU where the xfrm code is running.

## Advanced: filter a folded profile by CPU

```
perf record -b -e cycles,L1-dcache-load-misses,L1-icache-load-misses:k -g --call-graph dwarf
perf script > out.perf

cd Flamegraph
./stackcollapse-perf.pl ../out.perf > ../out.folded
grep cpuid out.kern_folded | ./flamegraph.pl > cpuid.svg
```

### New perf options tweked by LLM to add branch misses

```
perf record -b -e cycles,instructions,branches,branch-misses,cache-misses,L1-dcache-load-misses,L1-icache-load-misses,mem_load_retired.l3_miss,dtlb_load_miss_retired.l2,cycle_activity.stalls_mem_busy -g --call-graph dwarf
```

Here the plot is isolating cpus while recording all cpus,  stacks from a system-wide, multi-CPU capture before rendering the SVG.

## Example

See [xfrm_state_find() contention]({filename}2025-pcpu-testing-finland.md)
for an example flame graph generated using this method, and
[Brendan Gregg's page](https://www.brendangregg.com/FlameGraphs/cpuflamegraphs.html)
for more background on flame graphs.
</content>
