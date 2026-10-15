.PHONY: install test lint up down ingest eval kind-up kind-down helm-local verify-local open-local \
	server-setup sync-prod deploy-prod verify-prod verify-public logs-prod rollback-prod
PY ?= python3

install:            ## local venv with all dependencies
	$(PY) -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt

test:               ## unit tests, no API key needed
	.venv/bin/pytest -q

lint:
	.venv/bin/ruff check app scripts tests

up:                 ## API + Qdrant + demo page via Docker
	docker compose up --build -d

down:
	docker compose down

ingest:             ## (re)build the knowledge index
	docker compose run --rm api python -m scripts.ingest

eval:               ## run the eval set against Claude + Qdrant
	docker compose run --rm api python -m scripts.run_evals

kind-up:            ## local Kubernetes cluster to practise the Helm deployment
	kind create cluster --name pawsitivity

kind-down:          ## delete the local cluster
	kind delete cluster --name pawsitivity

# The API key is read from .env (or from the ANTHROPIC_API_KEY environment variable).
API_KEY = $(or $(ANTHROPIC_API_KEY),$(shell grep -E '^ANTHROPIC_API_KEY=' .env 2>/dev/null | cut -d= -f2-))

helm-local:         ## build the image and deploy it into the local kind cluster (SMALL=1: small-server profile)
	@test -n "$(API_KEY)" || (echo "ANTHROPIC_API_KEY missing in .env" && exit 1)
	docker build -t pawsitivity-rag:dev . && kind load docker-image pawsitivity-rag:dev --name pawsitivity
	helm repo add qdrant https://qdrant.github.io/qdrant-helm >/dev/null 2>&1 || true
	helm dependency update deploy/helm/pawsitivity-rag
	@# The key goes into a Kubernetes Secret (same as in production), never onto the helm command line.
	@kubectl create namespace pawsitivity --dry-run=client -o yaml | kubectl apply -f - >/dev/null
	@kubectl -n pawsitivity create secret generic pawsitivity-llm --from-literal=ANTHROPIC_API_KEY=$(API_KEY) \
	  --dry-run=client -o yaml | kubectl apply -f - >/dev/null
	helm upgrade --install pawsitivity-rag deploy/helm/pawsitivity-rag -n pawsitivity \
	  -f deploy/helm/pawsitivity-rag/values-local.yaml $(if $(SMALL),-f deploy/helm/pawsitivity-rag/values-small.yaml) \
	  --set secrets.existingSecret=pawsitivity-llm \
	  --set-string podRestart="$$(date +%s)" --wait --timeout 10m

verify-local:       ## run all checks against the local cluster
	./scripts/verify_k8s.sh

open-local:         ## chat with the cluster deployment in the browser (stop docker compose first: make down)
	@echo "Open http://localhost:8080 ; Ctrl+C to stop"
	@kubectl -n pawsitivity port-forward svc/pawsitivity-rag 8000:8000 >/dev/null & PF=$$!; \
	  trap "kill $$PF" EXIT INT TERM; python3 -m http.server 8080 --directory demo

# ---------------- production (Phase 3) ----------------
# HOST = server IP. IMAGE defaults to ghcr.io/<owner of the git remote "origin">/pawsitivity-rag
HOST ?=
EMAIL ?=
TAG ?= latest
# User for the one-time setup: root on most providers, ubuntu on OVHcloud
SETUP_USER ?= root
GH_OWNER = $(shell git remote get-url origin 2>/dev/null | sed -E 's#^(git@github.com:|https://github.com/)([^/]+)/.*#\2#' | tr A-Z a-z)
IMAGE ?= ghcr.io/$(or $(GH_OWNER),YOUR_GITHUB_USER)/pawsitivity-rag
QUESTION ?= Why are there no breed puppies for adoption?
need-host = @test -n "$(HOST)" || (echo "Set HOST, e.g.: make $@ HOST=1.2.3.4" && exit 1)

server-setup:       ## one-time server setup (k3s, firewall, cert-manager, API key); SETUP_USER=ubuntu on OVHcloud
	$(need-host)
	@test -n "$(EMAIL)" || (echo "Set EMAIL for Let's Encrypt, e.g.: make server-setup HOST=1.2.3.4 EMAIL=you@example.com" && exit 1)
	scp -r deploy/k3s $(SETUP_USER)@$(HOST):
	ssh -t $(SETUP_USER)@$(HOST) 'sudo bash k3s/bootstrap.sh $(EMAIL)'

sync-prod:
	$(need-host)
	ssh deploy@$(HOST) 'mkdir -p pawsitivity/chart'
	rsync -az --delete --exclude charts/ deploy/helm/pawsitivity-rag/ deploy@$(HOST):pawsitivity/chart/
	rsync -az deploy/k3s/deploy.sh scripts/verify_k8s.sh deploy@$(HOST):pawsitivity/

deploy-prod: sync-prod  ## deploy $(IMAGE):$(TAG) to the server
	ssh deploy@$(HOST) 'bash pawsitivity/deploy.sh $(IMAGE) $(TAG)'

verify-prod: sync-prod  ## checks inside the cluster (no pod deletion) + from the internet
	ssh deploy@$(HOST) 'cd pawsitivity && KUBECONFIG=$$HOME/.kube/config SKIP_CHAOS=1 ORIGIN=https://coexistwithpawsitivity.com QUESTION="$(QUESTION)" bash ./verify_k8s.sh'
	QUESTION="$(QUESTION)" ./scripts/verify_public.sh

verify-public:      ## only the checks from the internet (DNS, HTTPS, CORS, one question)
	QUESTION="$(QUESTION)" ./scripts/verify_public.sh

logs-prod:
	$(need-host)
	ssh deploy@$(HOST) 'KUBECONFIG=$$HOME/.kube/config kubectl -n pawsitivity logs deploy/pawsitivity-rag --tail=50'

rollback-prod:      ## go back to the previous release
	$(need-host)
	ssh deploy@$(HOST) 'helm -n pawsitivity rollback pawsitivity-rag && helm -n pawsitivity history pawsitivity-rag --max 3'
