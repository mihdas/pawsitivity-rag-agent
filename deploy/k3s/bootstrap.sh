#!/usr/bin/env bash
# One-time server setup for the Pawsitivity RAG agent. Run as root on a fresh Ubuntu 24.04 server:
#
#   make server-setup HOST=SERVER_IP EMAIL=you@example.com                    (providers that give you root)
#   make server-setup HOST=SERVER_IP EMAIL=you@example.com SETUP_USER=ubuntu  (e.g. OVHcloud: log in as ubuntu, sudo)
#
# What it does (safe to run again):
#   1. system updates + automatic security updates
#   2. firewall: only SSH, HTTP, HTTPS from outside; SSH with keys only
#   3. user "deploy" (used by `make deploy-prod` and GitHub Actions), same SSH keys as root
#   4. k3s (Kubernetes) with Traefik configured to keep the visitor's real IP (needed for rate limiting)
#   5. Helm, cert-manager and the Let's Encrypt issuer
#   6. namespace + Secret with your Anthropic API key (asked interactively, never stored in a file)

set -euo pipefail
EMAIL=${1:?"usage: bootstrap.sh you@example.com   (e-mail for Let's Encrypt expiry notices)"}
CERT_MANAGER_VERSION=v1.21.2
HERE=$(cd "$(dirname "$0")" && pwd)
NS=pawsitivity
say() { echo; echo "==> $*"; }

[[ $EUID -eq 0 ]] || { echo "Run as root (or with sudo)"; exit 1; }

# Your SSH key: from the sudo user (e.g. "ubuntu" on OVHcloud) if there is one, otherwise from root.
# Some providers put a "please log in as ubuntu" command in front of root's keys, so the sudo user's file wins.
KEYS=/root/.ssh/authorized_keys
if [[ -n "${SUDO_USER:-}" && "$SUDO_USER" != "root" && -s "/home/$SUDO_USER/.ssh/authorized_keys" ]]; then
  KEYS="/home/$SUDO_USER/.ssh/authorized_keys"
fi

say "1/6 System updates"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get upgrade -yq
apt-get install -yq ufw unattended-upgrades rsync curl ca-certificates python3
dpkg-reconfigure -f noninteractive unattended-upgrades

say "2/6 Firewall and SSH"
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow from 10.42.0.0/16 to any   # k3s pods
ufw allow from 10.43.0.0/16 to any   # k3s services
ufw --force enable
if [[ -s "$KEYS" ]]; then
  cat > /etc/ssh/sshd_config.d/10-hardening.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
EOF
  systemctl reload ssh || systemctl reload sshd
else
  echo "   WARNING: no SSH key found ($KEYS), password login left enabled. Add your SSH key and re-run."
fi

say "3/6 Deploy user"
id deploy >/dev/null 2>&1 || useradd --create-home --shell /bin/bash deploy
install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
if [[ -s "$KEYS" ]]; then
  touch /home/deploy/.ssh/authorized_keys
  # only plain key lines (no forced-command options)
  grep -E '^(ssh-|ecdsa-|sk-)' "$KEYS" | sort -u - /home/deploy/.ssh/authorized_keys -o /home/deploy/.ssh/authorized_keys
  chown deploy:deploy /home/deploy/.ssh/authorized_keys && chmod 600 /home/deploy/.ssh/authorized_keys
fi

say "4/6 k3s"
MEM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
if [[ $MEM_MB -lt 3000 ]]; then
  echo "   ${MEM_MB} MB RAM: small-server mode (2 GB swap, no metrics-server)"
  if ! swapon --show | grep -q .; then
    fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
    grep -q "^/swapfile" /etc/fstab || echo "/swapfile none swap sw 0 0" >> /etc/fstab
  fi
  echo "vm.swappiness=10" > /etc/sysctl.d/99-swappiness.conf && sysctl -q --system
  install -d /etc/rancher/k3s
  cat > /etc/rancher/k3s/config.yaml <<'K3SCONF'
disable:
  - metrics-server
kubelet-arg:
  - "fail-swap-on=false"
  - "system-reserved=memory=200Mi"
  - "eviction-hard=memory.available<100Mi"
K3SCONF
fi
if ! command -v k3s >/dev/null; then
  curl -sfL https://get.k3s.io | INSTALL_K3S_CHANNEL=stable sh -
fi
# Keep the client IP: without this every visitor looks like the same internal IP and shares one rate limit.
install -m 600 "$HERE/traefik-config.yaml" /var/lib/rancher/k3s/server/manifests/traefik-config.yaml
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
until kubectl get nodes 2>/dev/null | grep -q " Ready"; do sleep 3; done
kubectl get nodes
install -d -m 700 -o deploy -g deploy /home/deploy/.kube
install -m 600 -o deploy -g deploy /etc/rancher/k3s/k3s.yaml /home/deploy/.kube/config
grep -q "KUBECONFIG" /home/deploy/.bashrc 2>/dev/null || \
  sed -i '1i export KUBECONFIG=$HOME/.kube/config   # k3s kubectl would otherwise read the root-only file' /home/deploy/.bashrc

say "5/6 Helm, cert-manager, Let's Encrypt issuer"
command -v helm >/dev/null || curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
helm repo add jetstack https://charts.jetstack.io >/dev/null 2>&1 || true
helm repo update >/dev/null
helm upgrade --install cert-manager jetstack/cert-manager -n cert-manager --create-namespace \
  --version "$CERT_MANAGER_VERSION" --set crds.enabled=true \
  --set resources.requests.memory=32Mi --set webhook.resources.requests.memory=16Mi \
  --set cainjector.resources.requests.memory=32Mi --wait --timeout 10m
sed "s/YOUR_EMAIL@example.com/$EMAIL/" "$HERE/cluster-issuer.yaml" | kubectl apply -f -

say "6/6 Namespace and API key"
kubectl create namespace "$NS" --dry-run=client -o yaml | kubectl apply -f -
if kubectl -n "$NS" get secret pawsitivity-llm >/dev/null 2>&1 && [[ "${RESET_KEY:-}" != "1" ]]; then
  echo "   Secret pawsitivity-llm already exists (run with RESET_KEY=1 to replace it)."
else
  read -rsp "   Paste your Anthropic API key (input hidden): " KEY; echo
  [[ "$KEY" == sk-ant-* ]] || { echo "   That does not look like an Anthropic key."; exit 1; }
  kubectl -n "$NS" create secret generic pawsitivity-llm --from-literal=ANTHROPIC_API_KEY="$KEY" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  unset KEY
  echo "   Secret stored."
fi

say "Done. Next on your Mac:  make deploy-prod HOST=$(curl -s4 https://ifconfig.me || hostname -I | cut -d' ' -f1)"
