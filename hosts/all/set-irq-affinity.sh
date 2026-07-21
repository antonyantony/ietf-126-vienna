#! /bin/bash

service irqbalance stop

function usage
{
	echo "usage: $0 [--show] <interface> [<interface> ...]"
	echo "  --show show current irq/pci mapping, don't change affinity"
}

function get_driver
{
	ethtool -i $1 | awk -F': ' '/^driver:/{print $2}'
}

function get_bus_info
{
	ethtool -i $1 | awk -F': ' '/^bus-info:/{print $2}'
}

# Each get_irq_list_* prints one "IRQ QUEUE_KEY" pair per line. QUEUE_KEY
# groups IRQs that should share one core: normally the same as IRQ (one IRQ
# per queue), except virtio_net where input.N/output.N are separate IRQs for
# the same queue N and must share a core.

# mlx5_core (Mellanox ConnectX): completion-queue IRQs named e.g.
# "mlx5_comp0@pci:0000:01:00.0"
function get_irq_list_mlx5_core
{
	interface=$1
	bus_info=$(get_bus_info $interface)

	grep "$bus_info" /proc/interrupts | grep comp | awk '{sub(/:$/, "", $1); print $1, $1}'
}

# ixgbe / i40e / ice (Intel): queue IRQs named e.g. "eth0-TxRx-0"
function get_irq_list_txrx
{
	interface=$1

	grep "${interface}-TxRx-" /proc/interrupts | awk '{sub(/:$/, "", $1); print $1, $1}'
}

# ena (AWS Nitro): queue IRQs named e.g. "eth0-Tx-Rx-0"
function get_irq_list_ena
{
	interface=$1

	grep "${interface}-Tx-Rx-" /proc/interrupts | awk '{sub(/:$/, "", $1); print $1, $1}'
}

# virtio_net: queue IRQs share the PCI-MSIX-<bus-info> column, named e.g.
# "virtio1-input.0" / "virtio1-output.0"; exclude the "-config" control
# vector. input.N and output.N are paired onto the same core via QUEUE_KEY=N.
function get_irq_list_virtio_net
{
	interface=$1
	bus_info=$(get_bus_info $interface)

	grep "$bus_info" /proc/interrupts | grep -v -- '-config$' | awk '{
		irq = $1
		sub(/:$/, "", irq)
		name = $NF
		sub(/^.*\./, "", name)
		print irq, name
	}'
}

# fallback for unrecognized drivers: any IRQ line matching the NIC's PCI bus-info
function get_irq_list_generic
{
	interface=$1
	bus_info=$(get_bus_info $interface)

	grep "$bus_info" /proc/interrupts | awk '{sub(/:$/, "", $1); print $1, $1}'
}

function get_irq_list
{
	interface=$1
	driver=$(get_driver $interface)

	case "$driver" in
		mlx5_core)
			get_irq_list_mlx5_core $interface
			;;
		ixgbe|i40e|ice)
			get_irq_list_txrx $interface
			;;
		ena)
			get_irq_list_ena $interface
			;;
		virtio_net)
			get_irq_list_virtio_net $interface
			;;
		*)
			echo "Warning: no dedicated IRQ matcher for driver '$driver', using generic bus-info match" >&2
			get_irq_list_generic $interface
			;;
	esac
}

function set_irq_affinity
{
	irq_num=$1
	affinity=$2
	smp_affinity_path="/proc/irq/$irq_num/smp_affinity_list"
	echo $affinity > $smp_affinity_path

	i=$(cat $smp_affinity_path)
	echo "New affinity is $affinity, i: $i"
}

function show_irq_mapping
{
	interface=$1
	summary=$(ethtool -i $interface | awk -F': ' '/^(driver|version|bus-info):/{printf "%s: %s  ", $1, $2}')
	bus_info=$(get_bus_info $interface)
	queue_irqs=" $( get_irq_list $interface | awk '{print $1}' | tr '\n' ' ' ) "

	echo "$interface: $summary"

	grep "$bus_info" /proc/interrupts | while read -r line
	do
		IRQ=$(awk '{print $1}' <<< "$line" | sed 's/:$//')
		name=$(awk '{print $NF}' <<< "$line")
		affinity=$(cat /proc/irq/$IRQ/smp_affinity_list 2>/dev/null)

		case "$name" in
			*input*)  rank=1 ;;
			*output*) rank=2 ;;
			*)        rank=0 ;;
		esac

		if [[ "$queue_irqs" == *" $IRQ "* ]]; then
			suffix=""
		else
			suffix="  (control, not affinitized)"
		fi

		printf '%s\t%s\t  irq %s  %s  smp_affinity_list: %s%s\n' \
			"$rank" "$IRQ" "$IRQ" "$name" "$affinity" "$suffix"
	done | sort -t $'\t' -k1,1n -k2,2n | cut -f3-
}

SHOW=0
INTERFACES=()

while [ $# -gt 0 ]
do
	case "$1" in
		--show)
			SHOW=1
			shift
			;;
		-h|--help)
			usage
			exit 0
			;;
		-*)
			echo "Unknown option: $1"
			usage
			exit 1
			;;
		*)
			INTERFACES+=("$1")
			shift
			;;
	esac
done

if [ ${#INTERFACES[@]} -eq 0 ]; then
	usage
	exit 1
fi

if [ "$SHOW" -eq 1 ]; then
	for interface in "${INTERFACES[@]}"
	do
		show_irq_mapping $interface
	done
	exit 0
fi

echo "----------------------------"
echo "Setting trivial IRQ affinity"
echo "----------------------------"

core_id=-1
for interface in "${INTERFACES[@]}"
do
	echo "Discovered irqs for $interface:"
	prev_key="__new_interface__"

	while read -r IRQ key
	do
		if [ "$key" != "$prev_key" ]; then
			core_id=$(( core_id + 1 ))
			prev_key=$key
		fi

		echo "Assign irq $IRQ (queue $key) core_id $core_id"
		set_irq_affinity $IRQ $core_id
	done < <( get_irq_list $interface )
done

echo done.
