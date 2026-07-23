Title: 2026 pCPU using XDP CPUMAP (Vienna, 18-25 Jul)
Date: 2026-02-12
Summary: XDP redirection of traffic on ESP receiver

## Overview

This page provides a quick start for installing and testing XDP CPUMap.

## Prerequisites

- **Operating System:** Linux Kernel 7.1 or later pCPU was added i  6.12.
- **CPU:** Multi-core processor with NICs bound to the cores you are using
- **NIC** Driver that XDP in xdpdrv mode. i.e. run the xdp program on the host but in the context of driver, called back from linux  napi_poll.

```bash
sudo apt install -y clang llvm libelf-dev libpcap-dev build-essential pkg-config m4 gcc-multilib
```

```bash
cd linux/tools/bpf/bpftool
make install
```

```bash
apt install dwarves
```

## Installation

### Build XDP CPUMap

`Git repo https://github.com/antonyantony/xdp-tools  branch xfrm-antony-20260718`

```bash
cd xdp-tool
make
```

```bash
cd /home/antony/git/linux/tools/bpf/bpftool
make
make install
```

### Kernel Configuration

kernel config to enable

```bash
scripts/config --enable CONFIG_DEBUG_INFO_BTF
scripts/config --enable CONFIG_BPF_EVENTS
scripts/config --enable CONFIG_TRACEPOINTS
scripts/config --enable CONFIG_BPF_SYSCALL
scripts/config --enable CONFIG_HAVE_BPF_JIT
scripts/config --enable CONFIG_BPF_JIT
scripts/config --enable CONFIG_BPF_JIT
scripts/config --enable CONFIG_BPF_JIT_ALWAYS_ON
scripts/config --enable CONFIG_BPF_EVENTS
scripts/config --enable CONFIG_TRACEPOINTS
scripts/config --enable CONFIG_BPF_SYSCALL
scripts/config --enable CONFIG_TRACING
scripts/config --enable CONFIG_TRACEFS
scripts/config --enable CONFIG_TRACEPOINTS
scripts/config --enable CONFIG_BPF_EVENTS
scripts/config --enable CONFIG_KPROBE_EVENTS
scripts/config --enable CONFIG_DYNAMIC_FTRACE
scripts/config --enable CONFIG_FUNCTION_TRACER
scripts/config --enable CONFIG_STACKTRACE
scripts/config --enable CONFIG_BPF_EVENTS
```

### Debugging XFRM State Cache

```bt
root@west:~# cat /tmp/xfrm_cache.bt
kretprobe:xfrm_dst_check
  /retval != 0/
  {
      $dst = (struct dst_entry *)retval;
      $x = $dst->xfrm;
      if ($x != 0) {
          printf("cpu=%u cached=1 spi=0x%x\n", cpu, bswap($x->id.spi));
      }
  }

  kprobe:xfrm_state_look_at*
  {
      $a0 = (struct xfrm_state *)arg0;
      printf("cpu=%u cached=0 spi=0x%x\n", cpu, bswap($a0->id.spi));
  }
```

---

`bpftrace -e 'tracepoint:xdp:xdp_redirect {printf("xdp pathhit\n"); }'`

---

### Steering ESP Traffic to CPUs

`xdp-bench/xdp-bench redirect-cpu -v -p l4-sport --cpu-all red -s`

steer packets to Queues using ESP SPI.

`xdp-bench/xdp-bench redirect-cpu -v -p l4-sport --cpu-all red -s`

### KVM Virtio NIC Queues

KVM virtio NIC add queues add one line into interface section

```diff
     <interface type='bridge'>
       <mac address='12:00:00:64:64:23'/>
       <source bridge='brswan12-33232'/>
       <model type='virtio'/>
+      <driver name='vhost' queues='4'/>
       <address type='pci' domain='0x0000' bus='0x00' slot='0x03' function='0x0'/>
     </interface>
```

## History: 2023 AWS XDP Experiment

*(moved from rss-on-linux.md)*

= We used UDP encapsulation to overcome per flow limitation of AWS.

- [xdb-tools with spi based XDP_CPUREDIRECT
  support](https://github.com/antonyantony/xdp-tools/tree/xfrm-pcpu-v3-antony-20231108)
  2023 October

XDP is called from napi_poll

```bash
  export PRODUCTION=1;  ./configure
  ./xdp-bench/xdp-bench redirect-cpu  -p spi --cpu-all black  -Q
  ```

For diagnostics, build without `PRODUCTION=1` and run with `-v -s` (no `-Q`):

```bash
  ./configure
  ./xdp-bench/xdp-bench redirect-cpu  -v -p spi --cpu-all black  -s
```

L4 source port based distribution

\`\`\` ~/xdp-bench redirect-cpu -v -p l4-sport -q 4096 --cpu-all
eth0\`\`\` would distribute flows to different cpus Read the following
section for more on [XDP
cpump](https://github.com/xdp-project/xdp-cpumap-tc#assign-cpus-to-rx-queues)
or next section
