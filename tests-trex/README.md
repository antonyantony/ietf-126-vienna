Title: 2025 TRex Testing, (Finland 20 - 28 Aug)
Date: 2025-08-28
Summary: Quick start TRex testing

## Installing TRex : with Python3.9
I used TRex v3.06, as of July of 2025. It requires an older Python (3.8-3.9) than what is shipped in modern Linux distributios, such as Ubuntu 25.04. Mellanox NICs needs DOCA-OFED is also requred to  ConnectX NICs effectively. See the end for DOCA-OFED required configruation. TRex is install at  "/var/tmp/trex-v3.06" on sunset.

## Start TRex server
Pre-requieset:  Mellanox DOCA-OFED is started.<br>

Start the TRex server once and leave it running in the foreground. I prefer to run it inside a screen session. You can access it vis "screen -x and see the output". The server should be started in Python 3.9 venv.

### Login to sunset and start Python 3.9 venv
<pre>
cd /root
source ./venv/bin/activate
# To verify:
type python3.9; #python3.9 is hashed (/root/venv/bin/python3.9)
</pre>

I prefer to tart "screen bash" in this virtual environment. Inside the screen, and then start the TRex server.

### Start the TRex server
<pre>
cd /var/tmp/trex-v3.06
./t-rex-64 -i --no-scapy --cfg /etc/trex_cfg.yaml -c 8
</pre>

It will take a few seconds, and this will run in the foreground.

### Run TRex script
<pre>
cd /root/ietf-123-pcpu/tests-trex;
e.g.

./u1.py or

./u1.py --src-ip 192.0.1.253 --dst-ip 192.0.2.253 --pps 1M --frame-size 1518 --flows 2 --duration 10 --flows-end   2 --runs 2
</pre>

u1.py is my script. A simple UDP send and collect results in JSON. Then I use panda plots to generate plots.

## Mellanox NICs DOCA-OFED

Install DOCA-OFED following instructions from Mellanox website.

To start "mst start" # once.

Then the output should look something similarr.
<pre>
 mst status --v
MST modules:
------------
    MST PCI module is not loaded
    MST PCI configuration module loaded
    -E- Unknown argument "--v"
root@sunset:~/ietf-123-pcpu/tests-trex# mst status -v
MST modules:
------------
    MST PCI module is not loaded
    MST PCI configuration module loaded
PCI devices:
------------
DEVICE_TYPE             MST                           PCI       RDMA                                               NET                                     NUMA
ConnectX5(rev:0)        /dev/mst/mt4121_pciconf0.1    01:00.1   mlx5_1          net-                               redwest                             0

ConnectX5(rev:0)        /dev/mst/mt4121_pciconf0      01:00.0   mlx5_0          net-                               redeast                             0
</pre>
