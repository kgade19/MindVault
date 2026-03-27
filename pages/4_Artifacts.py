"""Page 4 — Knowledge Artifact Browser & Exporter."""
import json

import streamlit as st

from mindvault.database import sqlite_db as db

st.set_page_config(page_title="Artifacts · MindVault", page_icon="🧠", layout="wide")
db.init_db()

st.title("🗂️ Knowledge Artifacts")
st.caption("Browse, filter, and export all structured knowledge extracted from interviews and documents.")

# ── Filters ───────────────────────────────────────────────────────────────────
col_f1, col_f2, col_f3 = st.columns(3)

with col_f1:
    experts = db.get_experts()
    expert_options = {"All Experts": None} | {f"{e['name']} ({e['role']})": e["id"] for e in experts}
    selected_expert_label = st.selectbox("Expert", list(expert_options.keys()))
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
    selected_type_label = st.selectbox("Artifact Type", list(type_options.keys()))
    type_filter = type_options[selected_type_label]

with col_f3:
    search_term = st.text_input("Search title/content", placeholder="keyword…")

st.divider()

# ── Load artifacts ────────────────────────────────────────────────────────────
artifacts = db.get_artifacts(expert_id=expert_id_filter, artifact_type=type_filter, limit=500)

if search_term.strip():
    term = search_term.strip().lower()
    artifacts = [
        a for a in artifacts
        if term in a["title"].lower() or term in a["content"].lower()
    ]

# ── Stats ─────────────────────────────────────────────────────────────────────
st.metric("Matching Artifacts", len(artifacts))

# ── Export buttons ────────────────────────────────────────────────────────────
if artifacts:
    col_e1, col_e2, _ = st.columns([1, 1, 4])
    with col_e1:
        json_str = json.dumps(artifacts, indent=2, default=str)
        st.download_button(
            "⬇️ Export JSON",
            data=json_str,
            file_name="mindvault_artifacts.json",
            mime="application/json",
        )
    with col_e2:
        md_lines = [f"# MindVault Knowledge Artifacts\n"]
        for a in artifacts:
            md_lines.append(f"## [{a['artifact_type'].replace('_',' ').title()}] {a['title']}\n")
            md_lines.append(f"{a['content']}\n")
            if a.get("tags"):
                md_lines.append(f"**Tags:** {', '.join(a['tags'])}\n")
            md_lines.append(f"*Created: {a['created_at'][:10]}*\n\n---\n")
        md_str = "\n".join(md_lines)
        st.download_button(
            "⬇️ Export Markdown",
            data=md_str,
            file_name="mindvault_artifacts.md",
            mime="text/markdown",
        )

st.divider()

# ── Artifact cards ────────────────────────────────────────────────────────────
TYPE_ICONS = {
    "decision": "⚖️",
    "lesson_learned": "💡",
    "process": "⚙️",
    "named_entity": "🏷️",
    "open_question": "❓",
}

if not artifacts:
    st.info("No artifacts match your filters. Try adjusting the filters above.")
else:
    for art in artifacts:
        icon = TYPE_ICONS.get(art["artifact_type"], "🗂️")
        type_label = art["artifact_type"].replace("_", " ").title()
        with st.expander(f"{icon} **{art['title']}** _{type_label}_"):
            st.markdown(art["content"])
            col_m1, col_m2, col_m3 = st.columns(3)
            col_m1.caption(f"**Expert ID:** {art.get('expert_id', '—')}")
            col_m2.caption(f"**Created:** {art['created_at'][:10]}")
            if art.get("tags"):
                st.caption("**Tags:** " + " · ".join(f"`{t}`" for t in art["tags"]))
