import os
import requests

# Real public-domain OSHA construction safety publications — verified
# reachable and construction-relevant before adding here (not fabricated,
# not copyrighted building-code text like ACI 318/IBC which OSHA
# publications, as U.S. government works, are exempt from). Broadens the
# RAG spec Q&A demo beyond a single ingested document so citations aren't
# all resting on the same source.
DOCUMENTS = [
    {
        "filename": "OSHA_Fall_Protection.pdf",
        "url": "https://www.osha.gov/sites/default/files/publications/OSHA3146.pdf",
        "title": "Fall Protection in Construction (OSHA 3146)",
    },
    {
        "filename": "OSHA_Construction_Industry_Digest.pdf",
        "url": "https://www.osha.gov/sites/default/files/publications/OSHA2202.pdf",
        "title": "Construction Industry Digest (OSHA 2202)",
    },
    {
        "filename": "OSHA_Scaffold_Use.pdf",
        "url": "https://www.osha.gov/sites/default/files/publications/OSHA3150.pdf",
        "title": "A Guide to Scaffold Use in the Construction Industry (OSHA 3150)",
    },
]


def download_and_ingest_pdf(doc: dict, api_base: str):
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(data_dir, exist_ok=True)
    pdf_path = os.path.join(data_dir, doc["filename"])

    if not os.path.exists(pdf_path):
        print(f"Downloading {doc['title']} from {doc['url']}...")
        response = requests.get(doc["url"], stream=True, timeout=60)
        if response.status_code == 200:
            with open(pdf_path, "wb") as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)
            print(f"Downloaded to {pdf_path}")
        else:
            print(f"Failed to download {doc['title']}. Status: {response.status_code}")
            return
    else:
        print(f"{doc['title']} already exists at {pdf_path}")

    print(f"Sending {doc['title']} to backend for parsing and indexing...")
    api_url = f"{api_base}/api/v1/drawing/parse"

    with open(pdf_path, "rb") as f:
        files = {"file": (doc["filename"], f, "application/pdf")}
        data = {"is_tabular": False}
        res = requests.post(api_url, files=files, data=data, timeout=300)

    if res.status_code == 200:
        result = res.json()
        print(f"  Indexed {result.get('indexed_chunks')} chunks, {len(result.get('extracted_dimensions', []))} dimensions extracted.")
    else:
        print(f"  Error: {res.status_code} - {res.text}")


def ingest_project_documents(api_base: str):
    """Index the demo project's own drawings, RFIs and change orders.

    Retrieval over OSHA publications alone cannot answer a rebar-spacing
    question — those are safety publications and contain no dimensional
    tolerances, so Agent 7 correctly returned nothing and Agent 6 drafted
    uncited RFIs. A real project's document set is what carries that
    information, so the corpus needs both.

    These records are synthetic (see data/project_documents.json). Each one's
    `source` is suffixed "(demo project record)" before indexing, so the
    distinction between invented project paperwork and genuine public-domain
    standard text survives into every citation an engineer sees.
    """
    import json

    path = os.path.join(os.path.dirname(__file__), "..", "data", "project_documents.json")
    if not os.path.exists(path):
        print(f"No project document set at {path} — skipping.")
        return

    with open(path, "r", encoding="utf-8") as fh:
        docs = json.load(fh).get("documents", [])

    print(f"\nIndexing {len(docs)} project records...")
    for doc in docs:
        res = requests.post(
            f"{api_base}/api/v1/drawing/index",
            json={"document_id": doc["id"], "text_chunks": [doc["text"]],
                  "source": doc["source"], "project_id": "default-project"},
            timeout=120,
        )
        if res.status_code == 200:
            print(f"  {doc['id']}: {res.json().get('indexed_chunks')} chunk(s) — {doc['source']}")
        else:
            print(f"  {doc['id']}: error {res.status_code} - {res.text[:120]}")


if __name__ == "__main__":
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")
    for doc in DOCUMENTS:
        download_and_ingest_pdf(doc, api_base)
    ingest_project_documents(api_base)
