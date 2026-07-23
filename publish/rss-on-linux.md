# Receiver Side Scaling (RSS) support for IPsec/ESP

Receive Side Scaling
(RSS)[RSS](https://www.kernel.org/doc/Documentation/networking/scaling.txt)
would steer a flow to different ques. The receiver NIC should be able
steer different flows, based on SPI, into separate queues to prevent the
receiver from getting overwhelmed. We used Mellanex CX7 to test. Some
cards initially tested did not seems to support RSS for ESP flows,
instead only TCP and UDP. While figuring out RSS for these cards we
tried a bit different approch. ESP in UDP encapsulation, along with ESP
in UDP GRO patches we could see the flows getting distributed on the
receiver. And later on in Nov 2019 kernel version 5.5 ML5 drivers seems
to support ESP. [Mellonox
RSS](https://community.mellanox.com/s/article/Bluefield-IP-Forwarding-and-IPSEC-SPI-RSS).

### config ntuple Commands

Enable GRO. ideally you should be able to run the following command,

     ethtool -N <nic> rx-flow-hash esp4

Another argument is if the NIC agnostic the 16 bits of SPI, of ESP
packet, is aligned with UDP port number and should provide enough
entropy.

     ethtool -N eno2 rx-flow-hash udp4 sdfn

RSS should suppr ESP4, ESP6, ESP in UDP for both IPv4 and IPv6.

### Marvel Octeon2 support

[Octeon2 commit Linux
5.12](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=b9b7421a01d82c474227fce04f0468f1c70be306)

#### Mellanox support (maybe)

could be configured steer the flow to a specific Q

    ethtool --config-ntuple enp3s0f0 flow-type esp4 src-ip 192.168.1.1 dst-ip 192.168.1.2 spi 0xffffffff action 4

ntuple filtering of a UDP flow

    ethtool --config-ntuple <interface name> flow-type udp4 src-ip 192.168.1.1 dst-ip 192.168.10.2 src-port 2000 dst-port 2001 action 2 loc 33

[en_fs_ethtool.c](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/drivers/net/ethernet/mellanox/mlx5/core/en_fs_ethtool.c)

    case ESP_V4_FLOW:
       return MLX5E_TT_IPV4_IPSEC_ESP;

#### Intel X710 (ice driver) yes

- [ice: enable parsing IPSEC SPI headers for
  RSS](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=586006f996346e8a5a1ea80637ec949ceeea4ecbc)
  since V51.17. You may need /lib/firmware DDP support added in

[ice: Enable writing hardware filtering
tables](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=c90ed40cefe187a20fc565650b119aa696abc2ed)
and right firmware loaded.

[intel VF driver support
ESP4](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=527691bf0682d7ddcca77fc17dabd2fa090572ff)

[i40e_ethtool.c
ESP_V4_FLOW](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/drivers/net/ethernet/intel/i40e/i40e_ethtool.c)

    i40e_ethtool.c
     case ESP_V4_FLOW:
     case ESP_V6_FLOW:
      /* Default is src/dest for IP, no matter the L4 hashing */
      cmd->data |= RXH_IP_SRC | RXH_IP_DST;
      break

#### AWS ENA (not yet) use UDP Encap

[ena_ethtool.c](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/drivers/net/ethernet/amazon/ena/ena_ethtool.c)

    case ESP_V4_FLOW:
    case ESP_V6_FLOW:
     return -EOPNOTSUPP;

[ENA driver mention support CPU
indirection](https://github.com/amzn/amzn-drivers/issues/80) may be we
can use it as udp.

    The default hashing is currently Toeplitz.

    Starting from ena driver v2.2.1 the driver supports changing the hash key and hash function as well as the indirection table itself. The support is only for instance types that end with "n", for example C5n instances.

    Please note that changing the indirection table is supported on all instance types.

#### VMWare RSS ESP : yes

[vmxnet](https://docs.vmware.com/en/vSphere/6.7/solutions/vSphere-6.7.2cd6d2a77980cc623caa6062f3c89362/GUID-C500585C0560D28B71180A40A4767C57.html)

[vmxnet3 version 4
commit](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=d3a8a9e5c3b334d443e97daa59bb95c0b69f4794)

The vSphere 6.7 release includes vmxnet3 version 4, which supports some
new features. "RSS for ESP – RSS for encapsulating security payloads
(ESP) is now available in the vmxnet3 v4 driver. Performance testing of
this feature showed a 146% improvement in receive packets per second
during a test that used IPSEC and four receive queues."

#### Marvell octeontx2-af RSS ESP : yes

=

<https://lore.kernel.org/r/1611378552-13288-1-git-send-email-sundeep.lkml@gmail.com>

<https://lore.kernel.org/netdev/1611378552-13288-1-git-send-email-sundeep.lkml@gmail.com/>

    ethtool -U eth0 rx-flow-hash esp4 sdfn
    ethtool -U eth0 rx-flow-hash ah4 sdfn
    ethtool -U eth0 rx-flow-hash esp6 sdfn

#### Broadcom : no?

= It seems would hash IP address of the ESP flow.

#### Linux AWS XDP 2023 expeiriment

= We used UDP encapsulation to overcome per flow limitation of AWS.

- [xdb-tools with spi based XDP_CPUREDIRECT
  support](https://github.com/antonyantony/xdp-tools/tree/xfrm-pcpu-v3-antony-20231108)
  2023 October

\`\`\` ~/xdp-bench redirect-cpu -v -p l4-sport -q 4096 --cpu-all
eth0\`\`\` would distribute flows to different cpus Read the following
section for more on [XDP
cpump](https://github.com/xdp-project/xdp-cpumap-tc#assign-cpus-to-rx-queues)
or next section

## More Linux related information about RSS/XDP ..

- [XDP
  cpump](https://github.com/xdp-project/xdp-cpumap-tc#assign-cpus-to-rx-queues)
  General information XDP CPU Redirect.
- [XDP multibuf Jumbo/GRO/TSO support Netdev 0x14,
  2021](https://lpc.events/event/11/contributions/939/attachments/771/1551/xdp-multi-buff.pdf)
- [XDP multi-buffer support
  5.18](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=169e77764adc041b1dacba84ea90516a895d43b2)After
  this initial patch set in Linux 5.18 specific driver support with
  Jumbo and GRO are added : virtio, ice40, MLX5, and more.
- [xdb-tools with spi based XDP_CPUREDIRECT
  support](https://github.com/antonyantony/xdp-tools/tree/xfrm-pcpu-v3-antony-20231108)
  2023 October
- [Receive Side Scaling (RSS) with eBPF and CPUMAP, Lorenzo Bianconi,
  May 13,
  2021](https://developers.redhat.com/blog/2021/05/13/receive-side-scaling-rss-with-ebpf-and-cpumap)

## Future research/ideas

- Test with SR IOV and virtualisation(KVM): need systems with NIC that
  support SR IOV and RSS for ESP or at least UDP.
- Can IKE daemon use other flow distribution methods based on SPI???
  DPDK???
- another way of flow control???
  <https://doc.dpdk.org/dts/test_plans/link_flowctrl_test_plan.html>
- [RSS/RPS/RFS](https://garycplin.blogspot.com/2017/06/linux-network-scaling-receives-packets.html)
- DPDK RSS support