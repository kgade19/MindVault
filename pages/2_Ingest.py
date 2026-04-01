"""Page 2 — Multi-Source Document Ingestion."""
import hashlib
import io

import streamlit as st

from mindvault.database import sqlite_db as db
from mindvault.ingestion.audio_ingester import transcribe
from mindvault.ingestion.image_ingester import ingest_image
from mindvault.ingestion.pdf_parser import extract_text
from mindvault.ingestion.pipeline import run_pipeline
from mindvault.ingestion.url_fetcher import fetch_url

st.set_page_config(page_title="Ingest · MindVault", page_icon="🧠", layout="wide")
db.init_db()

st.title("📥 Ingest Knowledge")
st.caption("Import content from any source — structured knowledge artifacts are extracted automatically.")

# ── Expert selector ───────────────────────────────────────────────────────────
experts = db.get_experts()
if not experts:
    st.warning("No experts found. Please create an expert on the 👤 Experts page first.")
    st.stop()

expert_options = {f"{e['name']} ({e['role']})": e for e in experts}
selected_label = st.selectbox("Assign to Expert", list(expert_options.keys()))
expert = expert_options[selected_label]

# ── Project selector ──────────────────────────────────────────────────────────
# Parse key_projects text (newline- or comma-separated) into a list.
def _parse_projects(text: str) -> list[str]:
    if not text or not text.strip():
        return []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) > 1:
        return lines
    parts = [p.strip() for p in text.split(",") if p.strip()]
    return parts if len(parts) > 1 else ([text.strip()] if text.strip() else [])


key_projects = _parse_projects(expert.get("key_projects", ""))
if key_projects:
    project_options = key_projects + ["General / Other"]
    selected_project_label = st.selectbox("Tag to Project", project_options)
    if selected_project_label == "General / Other":
        resolved_project = st.text_input("Custom project tag", placeholder="optional").strip()
    else:
        resolved_project = selected_project_label
else:
    resolved_project = st.text_input(
        "Project tag (optional)",
        placeholder="e.g. Deployment pipeline, Vendor contracts…",
    ).strip()

st.divider()


def _run_pipeline(
    source_type: str,
    source_ref: str,
    title: str,
    content_text: str,
    sha256: str = "",
) -> None:
    """Common post-ingest pipeline: calls the shared run_pipeline() and renders results."""
    with st.spinner("Processing document…"):
        result = run_pipeline(
            expert_id=expert["id"],
            source_type=source_type,
            source_ref=source_ref,
            title=title,
            content_text=content_text,
            sha256=sha256,
            project=resolved_project,
        )

    if result["skipped"]:
        existing = result["existing"]
        st.warning(
            f"⚠️ Duplicate detected — this content was already ingested as "
            f"**{existing['title']}** on {existing['ingested_at'][:10]}. Skipping."
        )
        return

    artifacts = result["artifacts"]
    gaps = result["gaps"]
    n_chunks = result["n_chunks"]

    st.success(
        f"✅ Ingested **{title}** — {n_chunks} chunk(s) embedded, "
        f"{len(artifacts)} artifact(s) extracted."
    )

    if result["analysis_summary"]:
        with st.expander("📋 Document Summary", expanded=True):
            st.write(result["analysis_summary"])

    if artifacts:
        with st.expander(f"🗂️ {len(artifacts)} Extracted Artifacts", expanded=True):
            for art in artifacts:
                st.markdown(f"**[{art['artifact_type'].replace('_', ' ').title()}]** {art['title']}")
                st.caption(art["content"][:300] + ("…" if len(art["content"]) > 300 else ""))

    if gaps:
        with st.expander(f"⚠️ {len(gaps)} Knowledge Gaps Identified"):
            for gap in gaps:
                st.markdown(f"**{gap['gap_title']}**")
                st.write(gap["gap_description"])
                if gap.get("suggested_interview_questions"):
                    st.caption("Suggested follow-up questions:")
                    for q in gap["suggested_interview_questions"]:
                        st.caption(f"• {q}")


# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_pdf, tab_url, tab_text, tab_image, tab_audio = st.tabs(
    ["📄 PDF", "🌐 URL", "📝 Text / Markdown", "🖼️ Image", "🎵 Audio / Video"]
)

# ── PDF ───────────────────────────────────────────────────────────────────────
with tab_pdf:
    st.subheader("Upload a PDF")
    pdf_file = st.file_uploader("Choose a PDF file", type=["pdf"], key="pdf_upload")
    if pdf_file and st.button("Ingest PDF", type="primary", key="btn_pdf"):
        pdf_bytes = pdf_file.read()
        sha256 = hashlib.sha256(pdf_bytes).hexdigest()
        with st.spinner("Extracting PDF text…"):
            text = extract_text(pdf_bytes)
        if not text.strip():
            st.error("Could not extract any text from this PDF. It may be scanned — try the Image tab.")
        else:
            _run_pipeline("pdf", pdf_file.name, pdf_file.name, text, sha256)

# ── URL ───────────────────────────────────────────────────────────────────────
with tab_url:
    st.subheader("Fetch a Web Page")
    url_input = st.text_input("Enter URL", placeholder="https://…", key="url_input")
    if url_input and st.button("Fetch & Ingest", type="primary", key="btn_url"):
        with st.spinner(f"Fetching {url_input}…"):
            try:
                title, text = fetch_url(url_input)
            except Exception as exc:
                st.error(f"Failed to fetch URL: {exc}")
                st.stop()
        sha256 = hashlib.sha256(text.encode()).hexdigest()
        _run_pipeline("url", url_input, title, text, sha256)

# ── Text ──────────────────────────────────────────────────────────────────────
with tab_text:
    st.subheader("Paste Text or Markdown")
    text_title = st.text_input("Document Title", placeholder="Meeting notes, design doc, email…", key="text_title")
    text_body = st.text_area("Content", height=300, placeholder="Paste your text here…", key="text_body")
    if text_body.strip() and st.button("Ingest Text", type="primary", key="btn_text"):
        title = text_title.strip() or "Pasted text"
        sha256 = hashlib.sha256(text_body.encode()).hexdigest()
        _run_pipeline("text", title, title, text_body, sha256)

# ── Image ─────────────────────────────────────────────────────────────────────
with tab_image:
    st.subheader("Upload an Image")
    st.caption("AI vision analysis will extract all text and describe diagrams/charts.")
    img_file = st.file_uploader(
        "Choose an image", type=["png", "jpg", "jpeg", "webp", "gif"], key="img_upload"
    )
    if img_file and st.button("Analyse & Ingest", type="primary", key="btn_img"):
        img_bytes = img_file.read()
        sha256 = hashlib.sha256(img_bytes).hexdigest()
        st.image(img_bytes, caption=img_file.name, use_container_width=True)
        with st.spinner("Analysing image…"):
            try:
                text = ingest_image(img_bytes, filename=img_file.name)
            except Exception as exc:
                st.error(f"Image analysis failed: {exc}")
                st.stop()
        _run_pipeline("image", img_file.name, img_file.name, text, sha256)

# ── Audio ─────────────────────────────────────────────────────────────────────
with tab_audio:
    st.subheader("Upload Audio or Video")
    st.caption("The audio will be transcribed and structured knowledge artifacts extracted automatically.")
    audio_file = st.file_uploader(
        "Choose an audio/video file",
        type=["mp3", "wav", "ogg", "m4a", "webm", "mp4", "flac"],
        key="audio_upload",
    )
    if audio_file and st.button("Transcribe & Ingest", type="primary", key="btn_audio"):
        audio_bytes = audio_file.read()
        sha256 = hashlib.sha256(audio_bytes).hexdigest()
        with st.spinner("Transcribing audio (this may take a minute for large files)…"):
            try:
                text = transcribe(audio_bytes)
            except Exception as exc:
                st.error(f"Transcription failed: {exc}")
                st.stop()
        if not text.strip():
            st.warning("Transcription produced no text. The file may be silent or corrupt.")
        else:
            with st.expander("Transcript Preview"):
                st.text(text[:1000] + ("…" if len(text) > 1000 else ""))
            title = audio_file.name
            _run_pipeline("audio", audio_file.name, title, text, sha256)

st.divider()
st.caption("© 2026 Kiran Gade (KG). All rights reserved.")
