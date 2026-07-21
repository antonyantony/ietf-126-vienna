Title: Per-CPU IPsec SAs, Getting Started
Date: 2026-07-21
Summary: Software requirements, NIC tuning, and diagnosing steps for per-CPU IPsec SA testing

## Software requirements

- Linux Kernel 6.12 or later
- iproute2 7.0 or later
- libreswan (with per-CPU SA patches) or strongSwan 6.0.0 or later

## Network Interface (NIC) tuning

### Packet steering

TBD

### Enabling RSS

TBD

### Show IRQ distribution

<pre>
cat /proc/interrupts
</pre>

### Set IRQ distribution

<pre>
hosts/all/set-irq-affinity.sh &lt;interface&gt;
</pre>

## Diagnosing

### Red traffic

#### bpf traffic on incoming interface

TBD

### Black traffic

TBD

### Watch xfrm state usage

<pre>
hosts/all/xfrm-pcpu-watch.sh [interval_seconds]
</pre>

## Historic documents

- Libreswan and Linux XFRM Proof of concept
- [RSS and Friends on Linux](rss-on-linux.md)
