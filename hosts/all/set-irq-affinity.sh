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

# mlx5_core (Mellanox ConnectX): completion-queue IRQs named e.g.
# "mlx5_comp0@pci:0000:01:00.0"
function get_irq_list_mlx5_core
{
	interface=$1
	bus_info=$(get_bus_info $interface)

	grep "$bus_info" /proc/interrupts | grep comp | awk '{print $1}' | sed 's/:$//'
}

# ixgbe / i40e / ice (Intel): queue IRQs named e.g. "eth0-TxRx-0"
function get_irq_list_txrx
{
	interface=$1

	grep "${interface}-TxRx-" /proc/interrupts | awk '{print $1}' | sed 's/:$//'
}

# ena (AWS Nitro): queue IRQs named e.g. "eth0-Tx-Rx-0"
function get_irq_list_ena
{
	interface=$1

	grep "${interface}-Tx-Rx-" /proc/interrupts | awk '{print $1}' | sed 's/:$//'
}

# virtio_net: queue IRQs share the PCI-MSIX-<bus-info> column, named e.g.
# "virtio1-input.0" / "virtio1-output.0"; exclude the "-config" control vector
function get_irq_list_virtio_net
{
	interface=$1
	bus_info=$(get_bus_info $interface)

	grep "$bus_info" /proc/interrupts | grep -v -- '-config$' | awk '{print $1}' | sed 's/:$//'
}

# fallback for unrecognized drivers: any IRQ line matching the NIC's PCI bus-info
function get_irq_list_generic
{
	interface=$1
	bus_info=$(get_bus_info $interface)

	grep "$bus_info" /proc/interrupts | awk '{print $1}' | sed 's/:$//'
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
	queue_irqs=" $( get_irq_list $interface | tr '\n' ' ' ) "

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

core_id=0
for interface in "${INTERFACES[@]}"
do
	IRQS=$( get_irq_list $interface )

	echo Discovered irqs for $interface: $IRQS
	for IRQ in $IRQS
	do
		echo Assign irq $IRQ core_id $core_id
		set_irq_affinity $IRQ $core_id
		core_id=$(( core_id + 1 ))
	done
done

echo done.
