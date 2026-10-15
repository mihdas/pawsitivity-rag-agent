# Pawsitivity RAG Agent

Website assistant for **coexistwithpawsitivity.com**. It answers only from the content in `knowledge/` and refuses unrelated questions.

**Stack:** FastAPI · LangGraph · Claude Haiku 5.5 · Qdrant · Docker · Helm · k3s · GitHub Actions.

**The full plan, architecture and deployment steps are in [BLUEPRINT.md](BLUEPRINT.md).**

## Quick start

```bash
cd ~/Documents/pawsitivity-rag-agent
open -e .env                  # add ANTHROPIC_API_KEY (if .env is missing: cp .env.example .env)
# add your content to knowledge/   (see knowledge/README.md)
make up                       # API on :8000, Qdrant on :6333, demo page on :8080
make ingest                   # build the index
open http://localhost:8080
```

```bash
make install && make test     # unit tests, no API key needed
make eval                     # evaluation set against the real model
```

## Embed on the website

```html
<script src="https://chat.coexistwithpawsitivity.com/widget.js" data-color="#2f6f4f" defer></script>
```

## Project layout

```
app/            API (main.py), LangGraph agent (graph.py), guardrails, prompts, widget
config/         guardrails.yaml: scope, refusal texts, injection patterns
knowledge/      your content (Markdown, PDF, HTML, urls.txt)
scripts/        ingest.py, run_evals.py, verify_k8s.sh (checks a Kubernetes deployment)
evals/          cases.yaml: in-scope, out-of-scope and attack questions
tests/          unit tests with a fake LLM
deploy/helm/    Helm chart (API, ingest job, ingress, network policy, Qdrant dependency)
deploy/k3s/     server setup (bootstrap.sh), deploy.sh, Traefik and cert-manager config
demo/           local page that embeds the widget
```
