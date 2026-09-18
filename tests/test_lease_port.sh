#!/bin/sh
# Self-test for shared/scripts/lease-port - run with `mise run test-scripts`
# (needs python3 to occupy ports and shellcheck, both via mise tools).

set -eu
cd "$(dirname "$0")/.."

SCRIPT=shared/scripts/lease-port
HELD=""

cleanup() {
	# shellcheck disable=SC2086  # intentional word splitting of recorded PIDs
	kill $HELD >/dev/null 2>&1 || true
	wait >/dev/null 2>&1 || true
}
trap 'cleanup' EXIT INT TERM

fail() {
	printf 'FAIL - %s\n' "$1" >&2
	exit 1
}

hold() { # hold a port (background python3 listener, 60s) and wait until LISTEN
	python3 -c '
import socket, sys, time
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", int(sys.argv[1])))
s.listen(1)
time.sleep(60)
' "$1" &
	HELD="$HELD $!"
	i=0
	while [ "$i" -lt 100 ]; do
		if lsof -nP -iTCP:"$1" -sTCP:LISTEN -t >/dev/null 2>&1; then
			return 0
		fi
		i=$((i + 1))
		sleep 0.1
	done
	fail "port $1 never reached LISTEN"
}

in_range() {
	if [ "$(printf '%s' "$1" | tr -dc '0-9')" = "$1" ] &&
		[ "$1" -ge 8000 ] && [ "$1" -le 8999 ]; then
		return 0
	fi
	fail "'$1' is not a port in 8000-8999 ($2)"
}

command -v shellcheck >/dev/null 2>&1 || fail "shellcheck missing (run: mise install)"
shellcheck shared/scripts/lease-port tests/test_lease_port.sh || fail "shellcheck findings"

printf '1) scan returns a free port in range\n'
base=$(sh "$SCRIPT")
in_range "$base" "scan"

printf '2) free preferred port is returned verbatim\n'
[ "$(sh "$SCRIPT" "$base")" = "$base" ] || fail "preferred-if-free broken"

printf '3) occupied preferred port falls back to another port in range\n'
hold "$base"
other=$(sh "$SCRIPT" "$base")
in_range "$other" "fallback"
[ "$other" != "$base" ] || fail "returned the occupied preferred port"

printf '4) single-port range works free and busy (range override honored)\n'
busy_port="$(sh "$SCRIPT" 8600)"
in_range "$busy_port" "range probe"
hold "$busy_port"
out=$(FREE_PORT_MIN="$busy_port" FREE_PORT_MAX="$busy_port" sh "$SCRIPT" 2>/dev/null && printf ok || printf busy)
[ "$out" = "busy" ] || fail "occupied single-port range should exit non-zero"
free_port=8700
is_free_out=$(lsof -nP -iTCP:"$free_port" -sTCP:LISTEN -t 2>/dev/null || true)
[ -z "$is_free_out" ] || { free_port=$(sh "$SCRIPT"); }
out=$(FREE_PORT_MIN="$free_port" FREE_PORT_MAX="$free_port" sh "$SCRIPT")
[ "$out" = "$free_port" ] || fail "free single-port range should print it"

printf '5) invalid range and bad args are rejected\n'
out=$(FREE_PORT_MIN=9000 FREE_PORT_MAX=8000 sh "$SCRIPT" 2>/dev/null && printf ok || printf err)
[ "$out" = "err" ] || fail "min>max should exit non-zero"
out=$(sh "$SCRIPT" not-a-port 2>/dev/null && printf ok || printf err)
[ "$out" = "err" ] || fail "non-numeric preferred port should exit non-zero"

printf '\nALL TESTS PASSED\n'
