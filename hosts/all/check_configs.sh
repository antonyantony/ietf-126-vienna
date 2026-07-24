#!/usr/bin/env bash
#
# check_configs.sh - verify/enable/disable CONFIG_* symbols in a kernel .config
#
# Usage:
#   check_configs.sh -c .config [--xdp] [--nft] [--xfrm] [-v] [input_file]
#   check_configs.sh -c .config --enable-xdp    # scripts/config --enable + make oldconfig + verify
#   check_configs.sh -c .config --disable-xdp   # scripts/config --disable + make oldconfig + verify
#   cat list.txt | check_configs.sh -c .config
#   check_configs.sh -c .config CONFIG_FOO CONFIG_BAR
#
# Symbols to check come from any combination of:
#   - profile flags (--xdp, --nft, --xfrm, ...) selecting a built-in list
#     below in PROFILES
#   - an input file argument (free-form text, e.g. `scripts/config --enable
#     CONFIG_FOO` lines, or a plain list of CONFIG_* names)
#   - piped stdin (same formats as an input file)
#   - CONFIG_* names passed directly as arguments
#
# Each profile "name" in PROFILES gets three flags for free:
#   --name           check-only: report enabled/disabled/missing (default action)
#   --enable-name    scripts/config --enable each symbol, run make oldconfig,
#                    then verify every symbol ended up enabled
#   --disable-name   scripts/config --disable each symbol, run make oldconfig,
#                    then verify every symbol ended up disabled
#
# --enable-*/--disable-* run scripts/config and make against the kernel
# source tree that contains the config file (i.e. "$(dirname "$config_file")").
#
# With no flags/input/stdin at all (bare interactive invocation), the
# --xdp profile is used by default (check-only).
#
# Exit status: 0 on success, 1 if a symbol failed the check/verification.

set -euo pipefail

# --- profiles: name -> space-separated CONFIG_* symbols -------------------
# Add new profiles here; they become available as --<name>, --enable-<name>,
# and --disable-<name> automatically.
declare -A PROFILES
PROFILES[xdp]="
CONFIG_DEBUG_INFO_BTF
CONFIG_BPF_EVENTS
CONFIG_TRACEPOINTS
CONFIG_BPF_SYSCALL
CONFIG_HAVE_BPF_JIT
CONFIG_BPF_JIT
CONFIG_BPF_JIT_ALWAYS_ON
CONFIG_TRACING
CONFIG_TRACEFS
CONFIG_KPROBE_EVENTS
CONFIG_DYNAMIC_FTRACE
CONFIG_FUNCTION_TRACER
CONFIG_STACKTRACE
"
PROFILES[nft]=""   # TODO: fill in nftables CONFIG_* symbols
PROFILES[xfrm]=""  # TODO: fill in XFRM/IPsec CONFIG_* symbols

DEFAULT_PROFILE="xdp"

config_file=".config"
selected_profiles=()
extra_args=()
verbose=0
action=""

usage() {
	cat >&2 <<EOF
Usage: $0 [-c config_file] [--PROFILE | --enable-PROFILE | --disable-PROFILE] [-v] [input_file | CONFIG_* ...]

  -c, --config FILE     path to .config to check against (default: ./.config)
  --PROFILE             check-only: use a built-in symbol list; available: ${!PROFILES[*]}
  --enable-PROFILE      scripts/config --enable each symbol, make oldconfig, verify
  --disable-PROFILE     scripts/config --disable each symbol, make oldconfig, verify
  --list-profiles       show built-in profiles and their symbols, then exit
  -v, --verbose         print the per-symbol table (default: summary only)
  input_file            file of CONFIG_* names / free text (or "-" for stdin)
  CONFIG_* ...          symbol names given directly on the command line

With no profile flag, input file, or piped stdin, defaults to --$DEFAULT_PROFILE (check-only).
--enable-* and --disable-* run scripts/config + make oldconfig in the kernel
tree containing the config file; they cannot be combined with each other or
with a plain --PROFILE check flag in the same invocation.
Multiple sources (profiles + file + stdin + bare names) are merged for check-only mode.
EOF
	exit 1
}

list_profiles() {
	for name in "${!PROFILES[@]}"; do
		echo "--$name:"
		if [[ -z "${PROFILES[$name]// /}" ]]; then
			echo "  (not yet defined)"
		else
			# shellcheck disable=SC2086
			printf '  %s\n' ${PROFILES[$name]}
		fi
	done
	exit 0
}

set_action() {
	local wanted="$1"
	if [[ -n "$action" && "$action" != "$wanted" ]]; then
		echo "error: cannot combine --$action-* with --$wanted-* (or a plain check flag) in one invocation" >&2
		exit 1
	fi
	action="$wanted"
}

while [[ $# -gt 0 ]]; do
	case "$1" in
	-c|--config)
		config_file="$2"
		shift 2
		;;
	-h|--help)
		usage
		;;
	--list-profiles)
		list_profiles
		;;
	-v|--verbose)
		verbose=1
		shift
		;;
	--*)
		name="${1#--}"
		case "$name" in
		enable-*)
			pname="${name#enable-}"
			if [[ -v PROFILES[$pname] ]]; then
				set_action "enable"
				selected_profiles+=("$pname")
			else
				echo "error: unknown profile: --enable-$pname" >&2
				echo "available profiles: ${!PROFILES[*]}" >&2
				exit 1
			fi
			;;
		disable-*)
			pname="${name#disable-}"
			if [[ -v PROFILES[$pname] ]]; then
				set_action "disable"
				selected_profiles+=("$pname")
			else
				echo "error: unknown profile: --disable-$pname" >&2
				echo "available profiles: ${!PROFILES[*]}" >&2
				exit 1
			fi
			;;
		*)
			if [[ -v PROFILES[$name] ]]; then
				set_action "check"
				selected_profiles+=("$name")
			else
				echo "error: unknown option or profile: $1" >&2
				echo "available profiles: ${!PROFILES[*]}" >&2
				exit 1
			fi
			;;
		esac
		shift
		;;
	*)
		extra_args+=("$1")
		shift
		;;
	esac
done

action="${action:-check}"

if [[ ${#extra_args[@]} -gt 0 && "$action" != "check" ]]; then
	echo "error: --enable-*/--disable-* only take symbols from their profile, not extra input" >&2
	exit 1
fi

if [[ ! -f "$config_file" ]]; then
	echo "error: config file not found: $config_file" >&2
	exit 2
fi

# --- gather raw text to scan for CONFIG_* tokens ---------------------------
raw=""

for name in "${selected_profiles[@]}"; do
	raw+="${PROFILES[$name]}"$'\n'
done

for arg in "${extra_args[@]}"; do
	if [[ "$arg" == "-" ]]; then
		raw+=$(cat)$'\n'
	elif [[ -f "$arg" ]]; then
		raw+=$(cat "$arg")$'\n'
	else
		raw+="$arg"$'\n'
	fi
done

if [[ ${#selected_profiles[@]} -eq 0 && ${#extra_args[@]} -eq 0 ]]; then
	if [[ ! -t 0 ]]; then
		raw+=$(cat)$'\n'
	else
		echo "no profile/input given, defaulting to --$DEFAULT_PROFILE (config=$config_file, pwd=$PWD)" >&2
		raw+="${PROFILES[$DEFAULT_PROFILE]}"$'\n'
	fi
fi

# Extract unique CONFIG_* symbol names, preserving first-seen order.
mapfile -t symbols < <(grep -oE 'CONFIG_[A-Za-z0-9_]+' <<<"$raw" | awk '!seen[$0]++')

if [[ ${#symbols[@]} -eq 0 ]]; then
	echo "error: no CONFIG_* symbols found in input" >&2
	exit 2
fi

# get_symbol_state CONFIG_FILE SYMBOL -> sets STATE (enabled|set|disabled|missing) and VAL
get_symbol_state() {
	local cfg="$1" sym="$2" line
	line=$(grep -E "^${sym}=|^# ${sym} is not set$" "$cfg" || true)

	if [[ "$line" =~ ^${sym}=([ym])$ ]]; then
		STATE="enabled"
		VAL="${BASH_REMATCH[1]}"
	elif [[ "$line" =~ ^${sym}=(.+)$ ]]; then
		STATE="set"
		VAL="${BASH_REMATCH[1]}"
	elif [[ "$line" == "# ${sym} is not set" ]]; then
		STATE="disabled"
		VAL=""
	else
		STATE="missing"
		VAL=""
	fi
}

# check_symbols CONFIG_FILE SYM... -> tallies into enabled/disabled/missing/fail_list
# (fail_list = symbols that are not enabled; used for both check mode and
# post-enable verification)
check_symbols() {
	local cfg="$1"
	shift
	local sym
	for sym in "$@"; do
		get_symbol_state "$cfg" "$sym"
		case "$STATE" in
		enabled)
			[[ $verbose -eq 1 ]] && printf '%-45s enabled (=%s)\n' "$sym" "$VAL"
			enabled=$((enabled + 1))
			;;
		set)
			[[ $verbose -eq 1 ]] && printf '%-45s set but not enabled (=%s)\n' "$sym" "$VAL"
			disabled=$((disabled + 1))
			fail_list+=("$sym")
			;;
		disabled)
			[[ $verbose -eq 1 ]] && printf '%-45s disabled (not set)\n' "$sym"
			disabled=$((disabled + 1))
			fail_list+=("$sym")
			;;
		missing)
			[[ $verbose -eq 1 ]] && printf '%-45s MISSING (no such symbol in config)\n' "$sym"
			missing=$((missing + 1))
			fail_list+=("$sym")
			;;
		esac
	done
}

run_oldconfig() {
	local kernel_dir="$1"
	echo
	echo "Running: make -C $kernel_dir oldconfig (KCONFIG_CONFIG=$(basename -- "$config_file"))"
	KCONFIG_CONFIG="$(basename -- "$config_file")" make -C "$kernel_dir" oldconfig
}

require_kernel_tree() {
	local kernel_dir="$1"
	config_script="$kernel_dir/scripts/config"
	if [[ ! -x "$config_script" ]]; then
		echo "error: scripts/config not found (or not executable) at $config_script" >&2
		echo "  --enable-*/--disable-* must be run against a kernel source tree" >&2
		exit 2
	fi
	if [[ ! -f "$kernel_dir/Makefile" ]]; then
		echo "error: no Makefile in $kernel_dir; run this from a kernel source tree" >&2
		exit 2
	fi
}

do_check() {
	local enabled=0 disabled=0 missing=0
	local fail_list=()

	if [[ $verbose -eq 1 ]]; then
		printf '%-45s %s\n' "SYMBOL" "STATUS"
		printf '%-45s %s\n' "------" "------"
	fi

	check_symbols "$config_file" "${symbols[@]}"

	echo
	echo "Summary: ${#symbols[@]} checked, $enabled enabled, $disabled disabled, $missing missing"

	if [[ ${#fail_list[@]} -gt 0 ]]; then
		echo
		echo "Not enabled:"
		printf '  %s\n' "${fail_list[@]}"
		exit 1
	fi
	exit 0
}

do_enable() {
	local kernel_dir
	kernel_dir=$(dirname -- "$config_file")
	require_kernel_tree "$kernel_dir"

	echo "Enabling ${#symbols[@]} symbol(s) in $config_file:"
	printf '  %s\n' "${symbols[@]}"

	local args=() sym
	for sym in "${symbols[@]}"; do
		args+=(--enable "$sym")
	done
	"$config_script" --file "$config_file" "${args[@]}"

	run_oldconfig "$kernel_dir"

	echo
	echo "Verifying symbols were accepted..."
	local enabled=0 disabled=0 missing=0
	local fail_list=()
	if [[ $verbose -eq 1 ]]; then
		printf '%-45s %s\n' "SYMBOL" "STATUS"
		printf '%-45s %s\n' "------" "------"
	fi
	check_symbols "$config_file" "${symbols[@]}"

	echo
	echo "Summary: ${#symbols[@]} checked, $enabled enabled, $disabled disabled, $missing missing"

	if [[ ${#fail_list[@]} -gt 0 ]]; then
		echo
		echo "Not accepted by oldconfig:"
		printf '  %s\n' "${fail_list[@]}"
		exit 1
	fi
	echo "All requested symbols enabled."
	exit 0
}

do_disable() {
	local kernel_dir
	kernel_dir=$(dirname -- "$config_file")
	require_kernel_tree "$kernel_dir"

	echo "Disabling ${#symbols[@]} symbol(s) in $config_file:"
	printf '  %s\n' "${symbols[@]}"

	local args=() sym
	for sym in "${symbols[@]}"; do
		args+=(--disable "$sym")
	done
	"$config_script" --file "$config_file" "${args[@]}"

	run_oldconfig "$kernel_dir"

	echo
	echo "Verifying symbols were accepted..."
	local still_enabled=()
	if [[ $verbose -eq 1 ]]; then
		printf '%-45s %s\n' "SYMBOL" "STATUS"
		printf '%-45s %s\n' "------" "------"
	fi
	for sym in "${symbols[@]}"; do
		get_symbol_state "$config_file" "$sym"
		if [[ $verbose -eq 1 ]]; then
			printf '%-45s %s\n' "$sym" "${STATE}${VAL:+ (=$VAL)}"
		fi
		[[ "$STATE" == "enabled" ]] && still_enabled+=("$sym")
	done

	echo
	echo "Summary: ${#symbols[@]} checked, $(( ${#symbols[@]} - ${#still_enabled[@]} )) disabled, ${#still_enabled[@]} still enabled"

	if [[ ${#still_enabled[@]} -gt 0 ]]; then
		echo
		echo "Not accepted by oldconfig (still enabled):"
		printf '  %s\n' "${still_enabled[@]}"
		exit 1
	fi
	echo "All requested symbols disabled."
	exit 0
}

case "$action" in
check)
	do_check
	;;
enable)
	do_enable
	;;
disable)
	do_disable
	;;
esac
