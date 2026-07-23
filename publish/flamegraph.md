Title: Generating Flame Graphs for XFRM Performance Analysis (Vienna, 23 Jul)
Date: 2026-07-23
Author: Antony Antony
Summary: How to use perf and FlameGraph to profile CPU cycles and cache misses for XFRM/IPsec code paths.

## Prerequisites

- `perf`
- [FlameGraph](https://github.com/brendangregg/FlameGraph)
- Likely some perl modules for FlameGraph.

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
./stackcollapse-perf.pl ../out.perf > ../out.folded
grep cpuid out.kern_folded | ./flamegraph.pl > cpuid.svg
```

Here the plot is isolating cpus while recording all cpus,  stacks from a system-wide, multi-CPU capture before rendering the SVG.

## Example

See [xfrm_state_find() contention]({filename}2025-pcpu-testing-finland.md)
for an example flame graph generated using this method, and
[Brendan Gregg's page](https://www.brendangregg.com/FlameGraphs/cpuflamegraphs.html)
for more background on flame graphs.
</content>
