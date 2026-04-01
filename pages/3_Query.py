"""Page 3 — RAG Knowledge Query."""
import streamlit as st

from mindvault.database import sqlite_db as db
from mindvault.rag import retriever

st.set_page_config(page_title="Query · MindVault", page_icon="🧠", layout="wide")
db.init_db()

st.title("🔍 Query the Knowledge Base")
st.caption("Ask any question — get a cited answer synthesised from captured expert knowledge.")

# ── Filters ───────────────────────────────────────────────────────────────────
col_f1, col_f2 = st.columns(2)

with col_f1:
    experts = db.get_experts()
    expert_options = {"All Experts": None} | {f"{e['name']} ({e['role']})": e["id"] for e in experts}
    selected_expert_label = st.selectbox("Filter by Expert", list(expert_options.keys()))
    expert_id_filter = expert_options[selected_expert_label]

with col_f2:
    type_options = {
        "All Types": None,
        "Decisions": "decision",
        "Lessons Learned": "lesson_learned",
        "Processes": "process",
        "Named Entities": "named_entity",
        "Open Questions": "open_question",
    }
    selected_type_label = st.selectbox("Filter by Artifact Type", list(type_options.keys()))
    type_filter = type_options[selected_type_label]

st.divider()

# ── Search bar ────────────────────────────────────────────────────────────────
query = st.text_input(
    "Your question",
    placeholder="e.g. Why was PostgreSQL chosen over MySQL for the billing service?",
    label_visibility="collapsed",
)

col_search, col_clear = st.columns([1, 5])
with col_search:
    search_clicked = st.button("🔍 Search", type="primary", use_container_width=True)

if search_clicked and query.strip():
    with st.spinner("Searching knowledge base and synthesising answer…"):
        result = retriever.retrieve_and_synthesize(
            query=query.strip(),
            expert_id=expert_id_filter,
            artifact_type=type_filter,
        )

    # ── Answer ────────────────────────────────────────────────────────────────
    st.subheader("Answer")
    st.markdown(result["answer"])

    # ── Conflicts ─────────────────────────────────────────────────────────────
    if result["conflicts"]:
        st.warning("**⚠️ Conflicts Detected in Knowledge Base**")
        for conflict in result["conflicts"]:
            st.warning(f"• {conflict}")

    # ── Sources ───────────────────────────────────────────────────────────────
    if result["sources"]:
        st.divider()
        st.subheader(f"Sources ({len(result['sources'])})")
        for i, src in enumerate(result["sources"], 1):
            with st.expander(f"[Source {i}] {src['source_ref']}"):
                col_s1, col_s2 = st.columns(2)
                col_s1.caption(f"**Type:** {src['source_type']}")
                col_s2.caption(f"**Artifact:** {src['artifact_type'] or '—'}")
                st.text(src["snippet"])

elif search_clicked and not query.strip():
    st.error("Please enter a question before searching.")

st.divider()
st.caption("© 2026 Kiran Gade (KG). All rights reserved.")
