#!/usr/bin/env bash
# Runs ON THE SERVER as user "deploy". Called by `make deploy-prod` and by GitHub Actions.
#   ~/pawsitivity/deploy.sh ghcr.io/<user>/pawsitivity-rag <tag>
set -euo pipefail
IMAGE=${1:?image repository}
TAG=${2:-latest}
cd "$(dirname "$0")"
export KUBECONFIG=$HOME/.kube/config
helm repo add qdrant https://qdrant.github.io/qdrant-helm >/dev/null 2>&1 || true
helm dependency build chart >/dev/null 2>&1 || helm dependency update chart
# Servers with less than 3 GB RAM get the small-server profile automatically.
MEM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
EXTRA=()
if [[ $MEM_MB -lt 3000 || "${SMALL:-0}" == "1" ]]; then
  echo "Server has ${MEM_MB} MB RAM -> small-server profile (values-small.yaml)"
  EXTRA=(-f chart/values-small.yaml)
fi
helm upgrade --install pawsitivity-rag chart -n pawsitivity \
  -f chart/values-prod.yaml "${EXTRA[@]}" \
  --set image.repository="$IMAGE" --set image.tag="$TAG" \
  --set-string podRestart="$(date +%s)" \
  --wait --timeout 10m
helm -n pawsitivity history pawsitivity-rag --max 3
