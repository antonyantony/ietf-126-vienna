Goal: scalable IPsec throughput with multiple CPUs(without IPsec HW
offload)

Linux IPsec use a pair of SAs. Here the new idea is install identical
SAs, same traffic selectors and different SPI, per CPU. Let say there
are 2 CPUs in use, we would add 3 pairs SAs. In the out going direction
two, one on each CPU and a last resort one. The per-CPU SA can increase
IPsec throuput. The idea of per-CPU SA in the outgoing direction was
discussed at Linux IPsec workshop March 2019, in Prague. Steffen
Klassert gave a presentation.

A small group of people worked on a prototype of user space(IKE),
Libreswan, and Linux kernel, XFRM. The libreswan implementation call
this option "clones". In the Linux kernel it is call pCPU. These names
may change as we adopt the idea to include SA per TOS bits (8-64)
TCP/UDP DST port hashing(some how configure n flows to be distributed).

The tests were performed without using IPsec HW hardware offload to
separate the performance numbers of per-CPU SA's from hardware
interaction.

## Results

The test result, as of Nov 2019, show an aggregated throughput increase
that is linearly with the number of CPUs.

We tested using physical servers, using Mellonex CX4 NIC. These NICs
(using the latest Linux driver CX5) support RSS for ESP. In the tests,
the clear text traffic was generated using a hardware traffic generator
which sends traffic to the first IPsec gateway. The IPsec gateway
encrypts the traffic and send it to the second IPsec gateway. That
gateway decrypts the traffic into clear text and forwards the traffic to
the receiving end of the traffic generator.

    |Traffic Generator Sender|-----|IPsec Gateweay #1|=====ipsec 40Gbps link====|IPsec Gateway #2|---|Traffic Generator Receiver|

The initial measurements are: **15-16 Gbps with 3 CPU's. Also about 6
Gbps with single CPU**

## Test setup using libreswan + pCPU patched kernel

### Linux kernel source code with pCPU support

git clone --single-branch --branch xfrm-pcpu-v1
<https://git.kernel.org/pub/scm/linux/kernel/git/klassert/linux-stk.git>

## Kernel / xfrm future plans

- Release private branch at Steffen's repository for wider testing.
- Kernel support for IPsec rekey. One could rekey in any order - either
  a head SA or the sub SA.
- One main difference is when installing a new sub SA during a rekey,
  add_sa() would delete the old sub SA. Libreswan should not try to
  delete it. Or convince to Steffen to allow deleting an old sub SA.
- Ben would like to add feature bind a sub sa to a head SA?
- seems to need latest iproute2 otherwise "ip x s" may loop.

### Libreswan with clones support

    git clone --single-branch --branch clones-4 https://github.com/antonyantony/libreswan

Sample config [\|
ipsec.conf](https://github.com/antonyantony/libreswan/blob/clones-1/testing/pluto/ikev2-68-sa-clones/ipsec.conf)

    conn westnet-eastnet
        rightid=@east
            leftid=@west
            left=192.1.2.45
            right=192.1.2.23
        rightsubnet=192.0.2.0/24
        leftsubnet=192.0.1.0/24
        authby=secret
            clones=2
            auto=add
            nic-offload=no

Initiate the connection and test the multiple CPU IPsec SA's:

    ipsec auto --up westnet-eastnet
    taskset 0x1 ping -n -c 2 -I 192.0.1.254 192.0.2.254
    taskset 0x2 ping -n -c 2 -I 192.0.1.254 192.0.2.254

    ipsec trafficstatus

    ipsec trafficstatus
    006 #2: "westnet-eastnet-0", type=ESP, add_time=1234567890, inBytes=0, outBytes=0, id='@east'
    006 #4: "westnet-eastnet-1", type=ESP, add_time=1234567890, inBytes=168, outBytes=168, id='@east'
    006 #3: "westnet-eastnet-2", type=ESP, add_time=1234567890, inBytes=168, outBytes=168, id='@east'

NOTE: Both SA \#3 and \#4 should have outgoing traffic on it and \#2
should not have any traffic on dual cpu system.

## Future Libreswan plans

- Current support using clones=n requires both endpoints to have the
  same clone number. Future plan is to allow asymmetric configuration,
  such as one side using 8 clones on 4 CPUs and the other side using
  using 12 clones on 12 CPUs
- Match Rekey support behaviour between kernel and libreswan. Deleting
  sub and head SA during a rekey procedure needs to be worked out with
  kernel
- Complete support for ipsec auto --down and delete
- Prevent clone instance on their own to be manipulated using ipsec auto
  add\|delete\|down
- Ensure interoperability against IPsec gateways that do not support
  clone SA's, such as previous versions of libreswan without clone
  support.

## Linux kernel XFRM details

The changes are to the SAdb entry aka state, or SA. The new concept is
head SA and sub SA for the outgoing direction. These are supported with
additional XFRMA_SA_EXTRA_FLAGS, and attributes of the SADB entry. SPDB,
aka, policy can either point to the head SA if your policy has SPI in
it. Libreswan installed policy do not have SPI in it. You need only one
policy. Note libreswan might install multiple identical polices. And
this works too.

The head SA is a catch all SA. It is not associated to a specific CPU.
When there is N CPU, install N+1 SAs. One head SA and N sub SAs.

To add SADB entry you need extra attributes to the netlink calls, for
methods XFRM_MSG_NEWSA, XFRM_MSG_UPDSA, and XFRM_MSG_GETSA, only for the
outgoing SA.Installing incoming or receiving SA to the kernel remain
un-changed.

### XFRM_MSG_NEWSA head SA

XFRMA_SA_EXTRA_FLAGS includes the XFRM_SA_PCPU_HEAD flag

### XFRM_MSG_NEWSA sub SA

XFRMA_SA_EXTRA_FLAGS includes the XFRM_SA_PCPU_SUB and the new attribute
XFRMA_SA_PCPU set to the <cpu id>. CPU SA ID start from 0, and it is a
u32.

### XFRM_MSG_UPDSA

Both the head SA and the sub SAs need extra attributes:

- The head SA sets the XFRMA_SA_EXTRA_FLAGS to XFRM_SA_PCPU_HEAD
- The sub SA sets the XFRMA_SA_EXTRA_FLAGS to XFRM_SA_PCPU_SUB and
  XFRMA_SA_PCPU is set to <sub-sa-id>.

### XFRM_MSG_GETSA

This call only requires changes for sub SAs:

- The sub SA XFRMA_SA_EXTRA_FLAGS is set to XFRM_SA_PCPU_SUB and
  XFRMA_SA_PCPU is set to <sub-sa-id>.
- Set XFRMA_SRCADDR to the src addr

This is the call used by libreswan "ipsec trafficstatus" without this
changes it will not find the sub SAs.

## when nCPU \< nSAs

When there are 4 CPUs and the number of clones configured is 8, because
the other end has 8 CPUs. The head SA's list only has 4 places for sub
SAs. Libreswan should install only 4 outbound sub SA's and install 8
inbound sub SA's. This is a local policy and not affecting the remote
IPsec peer. From the view of the remote peer, 4 inbound SA's appear to
be unused. The remote peer can still use all its 8 outbound SAs. IPsec
SA's are negotiated as as bundle of one inbound and one outbound SA.
Both ends commit to receiving on their inbound SA's, but are free to
decide on which outbound SA's they will send traffic. This setup is
therefor compliant with RFC 7296.

In our example above, the IKE daemon on the 4-CPU machine has a list of
all 8 SA bundles, but will have installed only 4 outbound SA's along
with the 8 inbound SA's in the Linux kernel. The "ip xfrm state" will
show this.

## Supported Work loads

As of Nov 2019, to make full use of the cloned SA's, network traffic
load has to be distributed over different CPU's to take advantage of the
pCPU feature.

If the traffic is generated on the IPsec machine itself, the
application(s) need to be writing their traffic (eg using send() of
write() syscalls) running on different CPU's. This can often be steered
using the taskset or numctl commands.

For forwarded traffic, you need RSS support on the NIC receiving the
clear text. RSS will steer different flows onto different CPUs and this
use SA assigned the CPU. If all the traffic consists of one single flow,
the traffic will not be distributed over different CPUs - to avoid out
of order delivery.

### Can we distribute 4 tuple flows locally generated?

yes. See above.

## Receiver Side Scaling - RSS support

Receive Side Scaling
[(RSS)](https://www.kernel.org/doc/Documentation/networking/scaling.txt)
is required for pCPU. The receiver NIC should be able to steer different
flows, based on SPI, into separate queues (CPUs) to prevent the receiver
from getting overwhelmed. We used Mellanex CX4 to test. Some cards
initially tested did not seems to support RSS for ESP flows, instead
only TCP and UDP. While figuring out RSS for these cards we tried a bit
different approach. ESP in UDP encapsulation, along with ESP in UDP GRO
patches we could see the flows getting distributed on the receiver. And
later on in Nov 2019 kernel version 5.5 ML5 drivers seems to support
ESP. [Mellonox
RSS](https://community.mellanox.com/s/article/Bluefield-IP-Forwarding-and-IPSEC-SPI-RSS).

### RSS Commands

Enable GRO. ideally you should be able to run the following,

     ethtool -N <nic> rx-flow-hash esp4

Another argument is if the NIC agnostic the 16 bits of SPI, of ESP
packet, is aligned with UDP port number and should provide enough
entropy.

     ethtool -N eno2 rx-flow-hash udp4 sdfn

### Mellanox support (YES)

there is support for RSS and ESP4 and ESP6.

The ntuple pinning an ESP flow to specific CPU, incoming SA, is not
supported.

    ethtool --config-ntuple enp3s0f0 flow-type esp4 src-ip 192.168.1.1 dst-ip 192.168.1.2 spi 0xffffffff action 4 loc 10

for a UDP flow, ntuple filtering would look like :

    ethtool --config-ntuple <interface name> flow-type udp4 src-ip 192.168.1.1 dst-ip 192.168.10.2 src-port 2000 dst-port 2001 action 2 loc 33

[en_fs_ethtool.c](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/drivers/net/ethernet/mellanox/mlx5/core/en_fs_ethtool.c)

    case ESP_V4_FLOW:
       return MLX5E_TT_IPV4_IPSEC_ESP;

### [XFRM_pCPU_RSS](./Internals:-XFRM-pCPU-RSS) details

## Future research/ideas

- Test with SR IOV and virtualisation(KVM): need systems with NIC that
  support SR IOV and RSS for ESP or at least UDP.
- Software RSS <https://www.linux-kvm.org/page/Multiqueue>
- can IKE daemon use other flow distribution methods based on SPI???
  DPDK???
- another way of flow control???
  <https://doc.dpdk.org/dts/test_plans/link_flowctrl_test_plan.html>

### Install SA only for the CPUs that has workload

One line summary : Libreswan terminology clone connection with
auto=start.

In the current model libreswan is configured with clones=N. When the
connection comes up libreswan, as part of IKE_AUTH exchange, negotiates
the head SA. And immediately negotiate N sub SAs using CREATE_CHILD_SA,
"New Child SA, RFC 7296 \#1.3.1". To negotiate N sub SAs libreswan need
N CREATE_CHILD_SA exchanges, or round trip times. Note you could do this
simultaneously when IKE daemon supports IKE window grater than one. Next
question is do we need a SA for all CPUs? what if the workloads are only
on few CPUs, say CPU 2 and CPU 4. In the current implementation we can't
optimize this.

Lets say you have 72 cores, and mysql running only on CPU 2 and CPU 4
need sub SA. One idea is add the sa based acquire message. The message
would need new attribute CPU id.

There are two cases. 1 There is no head SA, Just a XFRM policy entry.
The first packet of a new flow arrives on CPU 4 that match policy. The
XFRM creates a larval state with a timeout, default 30s, sends an
acquire message to the IKE daemon, with the new attribute CPU id in it.
Pluto, the IKE daemon, start a new IKE negotiation. While the
negotiation, IKE_INIT and IKE_AUTH, is going on the traffic is dropped
or first packet is cached. The pluto first negotiates the head SA, in
IKE_AUTH, and installs the head SA. If the flow is continues next
packets will use the head SA. While pluto goes ahead and negotiates,
installs, sub SA for CPU 4. Then on sub SA for CPU 4 will be used by
traffic, ie traffic will switch to this sub SA from head SA.

Now new flow arrive on CPU 2. Here is a bit of XFRM magic. (detail,
larval may have expired or not, it does not matter). The policy is hit,
state look up will find the head sa, and further look up for sub SA for
CPU 2 will not find an SA. There is no sub SA 2. Then xfrm will create
an acquire message with CPU id 2 and send this message to pluto via
netlink. And state find returns head SA. The traffic would use the head
SA.

NOTE: there may be or may not be a larval state, in either case xfrm
code should send an acquire message.

When pluto receives an acquire with the CPU id 2, it will negotiate a
new sub SA and install to CPU 2. Then traffic will switch to sub SA 2.

The advantage of this method is SAs are installed only for the
CPU/core/thread that has that to encrypt.

This need a bit of extra code both in kernel and in libreswan, option
would auto=ondemand

2\. Connection initiation is not packet triggered instead
administratively started "ipsec auto --up eastnet-westnet. Then pluto
will install n+1 SA.

Alternative is install only head SA. And based on traffic install sub
SA. In this case when a cpu hit the traffic and look sub sa find_state()
will install larval to the list as a sub sa.