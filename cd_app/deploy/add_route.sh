#!/usr/bin/env bash
# Add (or update) a Cloudflare tunnel route + DNS for the rehoboth-evergreen
# tunnel, following ~/infra/cloudflare/README.md. Append-only and idempotent:
# it GETs the live ingress, inserts one rule before the catch-all (skipping if
# the hostname already exists), and PUTs the full config back. It never removes
# or reorders other sites' rules. Config is passed to python via temp files so
# there is no stdin conflict.
#
# Usage:  ./add_route.sh <subdomain> <zone> <container:port>
# Example: ./add_route.sh christian-doctrine ebenezer-isaac.com christian-doctrine-web:80
set -euo pipefail

SUB="${1:?subdomain}"; ZONE="${2:?zone}"; TARGET="${3:?container:port}"
HOST="${SUB}.${ZONE}"
ACCOUNT_ID="04311be9c3a0a3c33b864317cc080a71"
TUNNEL_ID="d67a743e-0df7-411a-8e2f-9e8603a791ce"
API="https://api.cloudflare.com/client/v4"

TUNNEL_TOKEN=$(sed -n '/BEGIN ARGO TUNNEL TOKEN/,/END ARGO TUNNEL TOKEN/p' ~/.cloudflared/cert.pem \
  | sed '1d;$d' | base64 -d | python3 -c "import sys,json; print(json.load(sys.stdin)['apiToken'])")
source ~/infra/.env  # CLOUDFLARE_API_TOKEN

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT

echo "== GET current ingress =="
curl -s "$API/accounts/$ACCOUNT_ID/cfd_tunnel/$TUNNEL_ID/configurations" \
  -H "Authorization: Bearer $TUNNEL_TOKEN" > "$TMP/cur.json"

python3 - "$TMP/cur.json" "$TMP/new.json" "$HOST" "$TARGET" <<'PY'
import sys, json
curf, newf, host, target = sys.argv[1:5]
cur = json.load(open(curf, encoding="utf-8"))
if not cur.get("success") or "config" not in (cur.get("result") or {}):
    print("ABORT: unexpected GET response:", json.dumps(cur)[:300]); sys.exit(2)
cfg = cur["result"]["config"]
ingress = cfg.get("ingress", [])
print(f"existing rules: {len(ingress)}")
if any(r.get("hostname") == host for r in ingress):
    print("PRESENT"); sys.exit(0)
idx = len(ingress)
for i, r in enumerate(ingress):
    if "hostname" not in r:
        idx = i; break
ingress.insert(idx, {"hostname": host, "service": f"http://{target}"})
cfg["ingress"] = ingress
json.dump({"config": cfg}, open(newf, "w", encoding="utf-8"))
print(f"WILL PUT {len(ingress)} rules (added {host} -> {target} at index {idx})")
PY

if [ -f "$TMP/new.json" ]; then
  echo "== PUT updated ingress =="
  curl -s -X PUT "$API/accounts/$ACCOUNT_ID/cfd_tunnel/$TUNNEL_ID/configurations" \
    -H "Authorization: Bearer $TUNNEL_TOKEN" -H "Content-Type: application/json" \
    --data @"$TMP/new.json" \
    | python3 -c "import sys,json; r=json.load(sys.stdin); print('ingress PUT success:', r.get('success')); [print('  err:', e) for e in r.get('errors',[])]"
else
  echo "ingress rule already present, not modified"
fi

echo "== DNS CNAME =="
ZONE_ID=$(curl -s "$API/zones?name=$ZONE" -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['result'][0]['id'])")
EXISTS=$(curl -s "$API/zones/$ZONE_ID/dns_records?name=$HOST" -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  | python3 -c "import sys,json; print(len(json.load(sys.stdin)['result']))")
if [ "$EXISTS" = "0" ]; then
  curl -s -X POST "$API/zones/$ZONE_ID/dns_records" \
    -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" -H "Content-Type: application/json" \
    -d "{\"type\":\"CNAME\",\"name\":\"$SUB\",\"content\":\"$TUNNEL_ID.cfargotunnel.com\",\"proxied\":true,\"ttl\":1}" \
    | python3 -c "import sys,json; r=json.load(sys.stdin); print('dns CNAME success:', r.get('success'))"
else
  echo "CNAME for $HOST already exists, skipping"
fi

echo "== verify (edge) =="; sleep 4
curl -s -o /dev/null -w "%{http_code}\n" --max-time 15 "https://$HOST/" || true