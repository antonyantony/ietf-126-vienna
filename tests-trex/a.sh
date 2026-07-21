#!/bin/bash
SUBDIR=results/20251016-ports/gro-enabled/
mkdir -p $SUBDIR
./u1.py --pps 3M --frame-size 128 --dst-ports 1 --duration 30 --csvfile $SUBDIR/trex-flows-1-frame-size-128-xfrm
./u1.py --pps 3M --frame-size 128 --dst-ports 2 --duration 30 --csvfile $SUBDIR/trex-flows-2-frame-size-128-xfrm
./u1.py --pps 3M --frame-size 128 --dst-ports 4 --duration 30 --csvfile $SUBDIR/trex-flows-4-frame-size-128-xfrm
./u1.py --pps 3M --frame-size 128 --dst-ports 8 --duration 30 --csvfile $SUBDIR/trex-flows-8-frame-size-128-xfrm
./u1.py --pps 3M --frame-size 128 --dst-ports 128 --duration 30 --csvfile $SUBDIR/trex-flows-128-frame-size-128-xfrm
./u1.py --pps 3M --frame-size 128 --dst-ports 256 --duration 30 --csvfile $SUBDIR/trex-flows-256-frame-size-128-xfrm
./u1.py --pps 3M --frame-size 128 --dst-ports 1024 --duration 30 --csvfile $SUBDIR/trex-flows-1024-frame-size-128-xfrm
./u1.py --pps 3M --frame-size 128 --dst-ports 4096 --duration 30 --csvfile $SUBDIR/trex-flows-4096-frame-size-128-xfrm
./u1.py --pps 3M --frame-size 128 --dst-ports 8192 --duration 30 --csvfile $SUBDIR/trex-flows-8192-frame-size-128-xfrm
./u1.py --pps 3M --frame-size 128 --dst-ports 16384 --duration 30 --csvfile $SUBDIR/trex-flows-16384-frame-size-128-xfrm
