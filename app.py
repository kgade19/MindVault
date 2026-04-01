"""MindVault — Home Dashboard."""
import streamlit as st

from mindvault.database.sqlite_db import get_stats, init_db

st.set_page_config(
    page_title="MindVault",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Initialise DB on every cold start
init_db()


def main() -> None:
    st.title("🧠 MindVault")
    st.caption("Knowledge Preservation Platform — capture, preserve, and query critical expertise")

    st.divider()

    # ── Live stats ────────────────────────────────────────────────────────────
    try:
        stats = get_stats()
    except Exception:
        stats = {"experts": 0, "sessions": 0, "artifacts": 0, "documents": 0}

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("👤 Experts", stats["experts"])
    col2.metric("🎙️ Interview Sessions", stats["sessions"])
    col3.metric("🗂️ Knowledge Artifacts", stats["artifacts"])
    col4.metric("📄 Documents Ingested", stats["documents"])

    st.divider()

    # ── Navigation cards ──────────────────────────────────────────────────────
    st.subheader("Where would you like to go?")
    c1, c2, c3, c4, c5 = st.columns(5)

    with c1:
        st.markdown("### 🎙️ Interview")
        st.write("Conduct an AI-guided adaptive interview with a departing subject-matter expert.")
        st.page_link("pages/1_Interview.py", label="Start Interview", icon="🎙️")

    with c2:
        st.markdown("### 📥 Ingest")
        st.write("Import knowledge from PDFs, web URLs, text, images, or audio recordings.")
        st.page_link("pages/2_Ingest.py", label="Ingest Document", icon="📥")

    with c3:
        st.markdown("### 🔍 Query")
        st.write("Ask questions about captured knowledge — get cited answers with conflict warnings.")
        st.page_link("pages/3_Query.py", label="Search Knowledge", icon="🔍")

    with c4:
        st.markdown("### 🗂️ Artifacts")
        st.write("Browse, filter, and export all structured knowledge artifacts.")
        st.page_link("pages/4_Artifacts.py", label="Browse Artifacts", icon="🗂️")

    with c5:
        st.markdown("### 👤 Experts")
        st.write("Manage expert profiles and view per-expert knowledge statistics.")
        st.page_link("pages/5_Experts.py", label="Manage Experts", icon="👤")

    st.divider()
    st.caption(
        "MindVault uses a large-language model for intelligent interviews and structured extraction, "
        "ChromaDB for semantic vector search, and SQLite for relational metadata. "
        "All data is stored locally — nothing leaves your machine."
    )
    st.caption("© 2026 Kiran Gade (KG). All rights reserved.")


main()
