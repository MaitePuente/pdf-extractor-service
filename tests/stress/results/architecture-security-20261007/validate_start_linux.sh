#!/bin/sh
set -eu
sh -n /work/scripts/start.sh
mkdir -p /tmp/bootstrap-audit
cat > /tmp/bootstrap-audit/docker <<'STUB'
#!/bin/sh
printf '%s\n' "$*" >> /tmp/bootstrap-audit/calls
case "$*" in
  'info --format '* ) [ "$MODE" != unavailable ] ;;
  'network inspect pdf-network') [ "$MODE" != missing ] ;;
  *' up --build '* ) [ "$MODE" != failed ] ;;
  *' port traefik 80') echo '127.0.0.1:53701' ;;
esac
STUB
chmod +x /tmp/bootstrap-audit/docker
export PATH="/tmp/bootstrap-audit:$PATH"
for MODE in existing missing failed unavailable; do
    export MODE
    : > /tmp/bootstrap-audit/calls
    if sh /work/scripts/start.sh > /tmp/bootstrap-audit/output 2>&1; then
        [ "$MODE" = existing ] || [ "$MODE" = missing ]
        grep -q 'http://localhost:53701/docs' /tmp/bootstrap-audit/output
        grep -q -- '--scale extractor=2 --wait --wait-timeout 150' /tmp/bootstrap-audit/calls
    else
        [ "$MODE" = failed ] || [ "$MODE" = unavailable ]
        ! grep -q 'port traefik' /tmp/bootstrap-audit/calls
    fi
    if [ "$MODE" = missing ]; then
        grep -q 'network create pdf-network' /tmp/bootstrap-audit/calls
    else
        ! grep -q 'network create pdf-network' /tmp/bootstrap-audit/calls
    fi
    printf '%s: PASS\n' "$MODE"
done
printf 'Linux shell syntax + bootstrap control flow PASS (Docker calls simulated).\n'
