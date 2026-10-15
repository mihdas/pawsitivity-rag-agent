"""Load everything in knowledge/ (and optionally pages from knowledge/urls.txt) into Qdrant.

Usage:
    python -m scripts.ingest              # rebuild the collection from knowledge/
    python -m scripts.ingest --dry-run    # only show what would be indexed

Supported files: .md .txt .pdf .html
Markdown/text files can start with front matter to set title and link:
    ---
    title: Adoption process
    url: https://coexistwithpawsitivity.com/adoption
    ---
"""

import argparse
import re
import sys
import uuid
from pathlib import Path

import yaml
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import get_settings  # noqa: E402

FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
SUPPORTED = {".md", ".txt", ".pdf", ".html", ".htm"}


def _html_to_text(html: str) -> tuple[str, str]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "form"]):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else ""
    text = re.sub(r"\n{3,}", "\n\n", soup.get_text("\n", strip=True))
    return title, text


def load_file(path: Path, base: Path) -> list[Document]:
    meta = {"source": str(path.relative_to(base)), "title": path.stem.replace("-", " ").replace("_", " ").title(),
            "url": ""}
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        pages = PdfReader(str(path)).pages
        return [Document(page_content=p.extract_text() or "", metadata={**meta, "page": i + 1})
                for i, p in enumerate(pages)]
    raw = path.read_text(encoding="utf-8", errors="ignore")
    if suffix in {".html", ".htm"}:
        title, text = _html_to_text(raw)
        meta["title"] = title or meta["title"]
        return [Document(page_content=text, metadata=meta)]
    m = FRONT_MATTER.match(raw)
    if m:
        meta.update({k: str(v) for k, v in (yaml.safe_load(m.group(1)) or {}).items()})
        raw = raw[m.end():]
    if suffix == ".md" and meta["title"] == path.stem.replace("-", " ").replace("_", " ").title():
        h1 = re.search(r"^#\s+(.+)$", raw, re.MULTILINE)
        if h1:
            meta["title"] = h1.group(1).strip()
    return [Document(page_content=raw, metadata=meta)]


def load_urls(urls_file: Path) -> list[Document]:
    import httpx

    docs = []
    for url in [u.strip() for u in urls_file.read_text().splitlines() if u.strip() and not u.startswith("#")]:
        resp = httpx.get(url, timeout=20, follow_redirects=True, headers={"User-Agent": "pawsitivity-ingest/1.0"})
        resp.raise_for_status()
        title, text = _html_to_text(resp.text)
        docs.append(Document(page_content=text, metadata={"source": url, "title": title or url, "url": url}))
        print(f"  fetched {url}")
    return docs


def build_chunks(knowledge_dir: Path, include_urls: bool = True) -> list[Document]:
    docs: list[Document] = []
    for path in sorted(knowledge_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUPPORTED and path.name.lower() != "readme.md":
            docs.extend(load_file(path, knowledge_dir))
    urls_file = knowledge_dir / "urls.txt"
    if include_urls and urls_file.exists():
        docs.extend(load_urls(urls_file))
    splitter = RecursiveCharacterTextSplitter(chunk_size=900, chunk_overlap=150,
                                              separators=["\n## ", "\n### ", "\n\n", "\n", ". ", " "])
    chunks = [c for c in splitter.split_documents(docs) if len(c.page_content.strip()) > 30]
    for i, c in enumerate(chunks):
        c.metadata["chunk"] = i
    return chunks


def run_ingest(include_urls: bool = True, dry_run: bool = False) -> int:
    """Rebuild the collection from knowledge/. Returns the number of indexed chunks."""
    s = get_settings()
    chunks = build_chunks(s.knowledge_dir, include_urls=include_urls)
    sources = sorted({c.metadata["source"] for c in chunks})
    print(f"{len(chunks)} chunks from {len(sources)} sources", flush=True)
    for src in sources:
        print(f"  - {src}", flush=True)
    if dry_run or not chunks:
        if not chunks:
            print("Nothing to index. Put your content into knowledge/ first.")
        return 0

    from langchain_qdrant import QdrantVectorStore

    from app.vectorstore import get_embeddings

    ids = [str(uuid.uuid5(uuid.NAMESPACE_URL, f"{c.metadata['source']}#{c.metadata['chunk']}")) for c in chunks]
    QdrantVectorStore.from_documents(chunks, get_embeddings(), ids=ids, url=s.qdrant_url, api_key=s.qdrant_api_key,
                                     collection_name=s.collection, force_recreate=True)
    print(f"Indexed into collection '{s.collection}' at {s.qdrant_url}", flush=True)
    return len(chunks)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-urls", action="store_true", help="skip knowledge/urls.txt")
    args = ap.parse_args()
    run_ingest(include_urls=not args.no_urls, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
