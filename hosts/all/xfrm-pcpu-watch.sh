#!/bin/bash
# Continuously poll `ip xfrm state` and print only "dir out" entries
# (reqid, pcpu-num, oseq) whose oseq changed since the last poll.
# Works for both IPv4 and IPv6 states since it never parses src/dst.
#
# Usage: xfrm-pcpu-out.sh [interval_seconds]

interval="${1:-1}"

declare -A last_oseq

extract() {
    ip xfrm state | awk '
    /^src / { reqid=""; oseq=""; dir=""; spi="" }
    /reqid/ {
        for (i=1;i<=NF;i++) if ($i=="spi") spi=$(i+1)
        for (i=1;i<=NF;i++) if ($i=="reqid") reqid=$(i+1)
    }
    /anti-replay context/ {
        for (i=1;i<=NF;i++) if ($i=="oseq") { oseq=$(i+1); sub(/,$/,"",oseq) }
    }
    /[[:space:]]dir / {
        for (i=1;i<=NF;i++) if ($i=="dir") dir=$(i+1)
    }
    /pcpu-num/ {
        for (i=1;i<=NF;i++) if ($i=="pcpu-num") pcpu=$(i+1)
        if (dir=="out") print reqid, oseq, pcpu, spi
    }
    '
}

while true; do
    while read -r reqid oseq pcpu spi; do
        [ -z "$reqid" ] && continue
        key="${reqid}:${pcpu}"
        if [ "${last_oseq[$key]}" != "$oseq" ]; then
            printf 'pcpu-num=%s oseq=%s spi=%s\n' \
                "$pcpu" "$oseq" "$spi"
            last_oseq[$key]="$oseq"
        fi
    done < <(extract)
    sleep "$interval"
done
