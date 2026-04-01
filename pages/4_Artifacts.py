"""Page 4 — Knowledge Artifact Browser & Exporter."""
import json

import streamlit as st

from mindvault.database import sqlite_db as db

st.set_page_config(page_title="Artifacts · MindVault", layout="wide")
db.init_db()

st.title("Knowledge Artifacts")
st.caption("Browse, filter, and export all structured knowledge extracted from interviews and documents.")

# ── Build lookup maps used in filters and cards ───────────────────────────────
experts = db.get_experts()
expert_map = {e["id"]: e for e in experts}

# Index all sessions by id so cards can show what project an artifact belongs to.
session_map: dict[int, dict] = {}
for _e in experts:
    for _s in db.get_sessions_for_expert(_e["id"]):
        session_map[_s["id"]] = _s

# ── Filters ───────────────────────────────────────────────────────────────────
col_f1, col_f2, col_f3 = st.columns(3)

with col_f1:
    expert_options = {"All Experts": None} | {f"{e['name']} ({e['role']})": e["id"] for e in experts}
    selected_expert_label = st.selectbox("Expert", list(expert_options.keys()))
    expert_id_filter = expert_options[selected_expert_label]

with col_f2:
    departments = sorted({e["department"] for e in experts if e.get("department")})
    dept_options = {"All Departments": None} | {d: d for d in departments}
    selected_dept_label = st.selectbox("Department", list(dept_options.keys()))
    dept_filter = dept_options[selected_dept_label]

with col_f3:
    type_options = {
        "All Types": None,
        "Heuristic": "heuristic",
        "If-Then Rule": "if_then_rule",
        "Case Example": "case_example",
        "Red Flag": "red_flag",
        "Mental Model": "mental_model",
        "Exception": "exception",
        "Decision Factor": "decision_factor",
    }
    selected_type_label = st.selectbox("Artifact Type", list(type_options.keys()))
    type_filter = type_options[selected_type_label]

col_f4, col_f5 = st.columns([1, 2])

with col_f4:
    all_projects = db.get_all_session_topics()
    project_options = {"All Projects": None} | {p: p for p in all_projects}
    selected_project_label = st.selectbox("Project", list(project_options.keys()))
    project_filter = project_options[selected_project_label]

with col_f5:
    search_term = st.text_input("Search title/content", placeholder="keyword…")

st.divider()

# ── Load and filter artifacts ─────────────────────────────────────────────────
artifacts = db.get_artifacts(
    expert_id=expert_id_filter,
    artifact_type=type_filter,
    project=project_filter,
    limit=500,
)

# Department filter is post-fetch because department lives on experts, not artifacts.
if dept_filter:
    dept_expert_ids = {e["id"] for e in experts if e.get("department") == dept_filter}
    artifacts = [a for a in artifacts if a.get("expert_id") in dept_expert_ids]

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
            "Export JSON",
            data=json_str,
            file_name="mindvault_artifacts.json",
            mime="application/json",
        )
    with col_e2:
        md_lines = ["# MindVault Knowledge Artifacts\n"]
        for a in artifacts:
            expert_info = expert_map.get(a.get("expert_id", 0), {})
            art_topic = session_map.get(a.get("session_id"), {}).get("topic", "")
            type_label = a["artifact_type"].replace("_", " ").title()
            md_lines.append(f"## [{type_label}] {a['title']}\n")
            md_lines.append(f"{a['content']}\n")
            if expert_info:
                md_lines.append(f"**Expert:** {expert_info.get('name', '')} · {expert_info.get('department', '')}\n")
            if art_topic:
                md_lines.append(f"**Project:** {art_topic}\n")
            if a.get("tags"):
                md_lines.append(f"**Tags:** {', '.join(a['tags'])}\n")
            md_lines.append(f"*Created: {a['created_at'][:10]}*\n\n---\n")
        md_str = "\n".join(md_lines)
        st.download_button(
            "Export Markdown",
            data=md_str,
            file_name="mindvault_artifacts.md",
            mime="text/markdown",
        )

st.divider()

# ── Artifact cards ────────────────────────────────────────────────────────────
TYPE_LABELS = {
    "heuristic": "Heuristic",
    "if_then_rule": "If-Then Rule",
    "case_example": "Case Example",
    "red_flag": "Red Flag",
    "mental_model": "Mental Model",
    "exception": "Exception",
    "decision_factor": "Decision Factor",
}

if not artifacts:
    st.info("No artifacts match your filters. Try adjusting the filters above.")
else:
    for art in artifacts:
        type_label = TYPE_LABELS.get(art["artifact_type"], art["artifact_type"].replace("_", " ").title())
        expert_info = expert_map.get(art.get("expert_id", 0), {})
        expert_name = expert_info.get("name", "Unknown")
        expert_dept = expert_info.get("department", "")
        expert_display = f"{expert_name} · {expert_dept}" if expert_dept else expert_name
        art_topic = session_map.get(art.get("session_id"), {}).get("topic", "")
        confidence = float(art.get("confidence", 1.0))

        with st.expander(f"**{art['title']}** — {type_label}"):
            st.markdown(art["content"])
            col_m1, col_m2, col_m3, col_m4 = st.columns(4)
            col_m1.caption(f"**Expert:** {expert_display}")
            col_m2.caption(f"**Project:** {art_topic or '—'}")
            col_m3.caption(f"**Confidence:** {confidence * 100:.0f}%")
            col_m4.caption(f"**Created:** {art['created_at'][:10]}")
            if art.get("tags"):
                st.caption("**Tags:** " + " · ".join(f"`{t}`" for t in art["tags"]))

st.divider()
st.caption("© 2026 Kiran Gade (KG). All rights reserved.")
