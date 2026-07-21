#! /bin/bash

service irqbalance stop

if [ -z $1 ]; then
	echo "usage: $0 <interface>"
	exit 1
fi

function get_irq_list
{
	interface=$1

	cat /proc/interrupts | grep $(ethtool -i $interface | grep bus-info | awk -F ' ' '{print $2}') | grep comp | awk -F ' ' '{print $1}' | sed 's/.$//'
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

INT1=$1

echo "----------------------------"
echo "Setting trivial IRQ affinity"
echo "----------------------------"

IRQS_1=$( get_irq_list $INT1 )

echo Discovered irqs for $INT1: $IRQS_1
core_id=0
for IRQ in $IRQS_1
do
	echo Assign irq $IRQ core_id $core_id
	set_irq_affinity $IRQ $core_id
	core_id=$(( core_id + 1 ))
done

echo done.

