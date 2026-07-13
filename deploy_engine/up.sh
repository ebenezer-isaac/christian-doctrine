#!/usr/bin/env bash
# Bring up the doctrine engine on the VPS: the two air-gapped stacks (with
# serving-tuned memory) reusing the migrated data volumes, then cd_mcp. Run from
# the engine root (sites/christian-doctrine-engine); reads .env for Neo4j creds.
set -euo pipefail
cd "$(dirname "$0")/.."

# Export Neo4j creds so compose interpolates them regardless of .env discovery.
set -a; [ -f .env ] && . ./.env; set +a

echo "== lexical stack =="
docker compose -f docker/lexical/docker-compose.yml -f docker/lexical/docker-compose.vps.yml up -d
echo "== cultural stack =="
docker compose -f docker/cultural/docker-compose.yml -f docker/cultural/docker-compose.vps.yml up -d

echo "== wait for neo4j health =="
for name in lexical-neo4j cultural-neo4j; do
  for i in $(seq 1 40); do
    h=$(docker inspect --format '{{.State.Health.Status}}' "$name" 2>/dev/null || echo none)
    [ "$h" = healthy ] && { echo "$name healthy"; break; }
    sleep 5
  done
done

echo "== cd-mcp =="
docker compose -f deploy_engine/docker-compose.cdmcp.yml up -d --build

sleep 6
docker ps --format '{{.Names}} :: {{.Status}}' | grep -E 'lexical-neo4j|cultural-neo4j|lexical-qdrant|cultural-qdrant|cd-mcp' || true
