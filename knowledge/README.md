# Knowledge base

Everything in this folder is what the assistant knows. Nothing else.

* Put one topic per file: `about.md`, `team.md`, `services.md`, `faq.md`, `contact.md`, ...
* Supported: `.md`, `.txt`, `.pdf`, `.html`
* Start Markdown files with front matter so answers can link to the right page:

```
---
title: About us
url: https://coexistwithpawsitivity.com/about
---
# About us
...
```

* Optional: list public pages of the website in `urls.txt` (one URL per line) and they are
  downloaded and indexed during ingestion.
* FAQ format works best: a `## Question` heading followed by the answer.
* After changing anything here: `make ingest` (local) or push to `main` (production rebuilds the index).
* This README and files ending in `.example` are not indexed.
