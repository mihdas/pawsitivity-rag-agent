from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_qdrant import QdrantVectorStore

from scripts.ingest import build_chunks


def test_front_matter_html_and_ignored_files(tmp_path):
    (tmp_path / "README.md").write_text("# not indexed")
    (tmp_path / "about.md.example").write_text("not indexed either")
    (tmp_path / "faq.md").write_text(
        "---\ntitle: FAQ\nurl: https://coexistwithpawsitivity.com/faq\n---\n"
        "# FAQ\n\n## Can I bring my dog?\nYes, dogs on a leash are always welcome at our events.\n")
    (tmp_path / "team.html").write_text(
        "<html><head><title>Our team</title><script>x()</script></head>"
        "<body><nav>menu</nav><p>Our team has cared for rescued animals for many years.</p></body></html>")

    chunks = build_chunks(tmp_path, include_urls=False)
    by_title = {c.metadata["title"]: c for c in chunks}

    assert set(by_title) == {"FAQ", "Our team"}
    assert by_title["FAQ"].metadata["url"] == "https://coexistwithpawsitivity.com/faq"
    assert "title:" not in by_title["FAQ"].page_content
    assert "menu" not in by_title["Our team"].page_content and "x()" not in by_title["Our team"].page_content


def test_chunks_round_trip_through_qdrant(tmp_path):
    (tmp_path / "faq.md").write_text("# FAQ\n\n## Opening hours\nWe are open Monday to Friday from 9 to 17.\n")
    chunks = build_chunks(tmp_path, include_urls=False)
    store = QdrantVectorStore.from_documents(chunks, DeterministicFakeEmbedding(size=64), location=":memory:",
                                             collection_name="t")
    hits = store.similarity_search_with_score("Opening hours", k=1)
    assert hits and "Monday" in hits[0][0].page_content
