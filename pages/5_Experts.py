"""Page 5 — Expert Profile Management."""
import streamlit as st

from mindvault.database import sqlite_db as db

st.set_page_config(page_title="Experts · MindVault", page_icon="🧠", layout="wide")
db.init_db()

st.title("👤 Expert Profiles")
st.caption("Create and manage the subject-matter experts whose knowledge is being preserved.")

# ── Create new expert ─────────────────────────────────────────────────────────
with st.expander("➕ Create New Expert", expanded=not bool(db.get_experts())):
    with st.form("create_expert_form"):
        c1, c2 = st.columns(2)
        name = c1.text_input("Full Name *", placeholder="Jane Smith")
        role = c2.text_input("Role / Title *", placeholder="Principal Engineer")
        c3, c4 = st.columns(2)
        department = c3.text_input("Department", placeholder="Platform Engineering")
        _ = c4.empty()
        notes = st.text_area("Notes", placeholder="Brief bio, areas of expertise, key projects…", height=80)
        submitted = st.form_submit_button("Create Expert", type="primary")
        if submitted:
            if not name.strip() or not role.strip():
                st.error("Name and Role are required.")
            else:
                db.create_expert(name.strip(), role.strip(), department.strip(), notes.strip())
                st.success(f"Expert **{name}** created!")
                st.rerun()

st.divider()

# ── Expert list ───────────────────────────────────────────────────────────────
experts = db.get_experts()

if not experts:
    st.info("No experts yet. Create the first expert above to get started.")
    st.stop()

for expert in experts:
    sessions = db.get_sessions_for_expert(expert["id"])
    artifacts = db.get_artifacts(expert_id=expert["id"])
    docs = db.get_documents(expert_id=expert["id"])
    completed = sum(1 for s in sessions if s["status"] == "completed")

    with st.expander(f"**{expert['name']}** — {expert['role']} · {expert['department']}"):
        # Stats row
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("Sessions", len(sessions), help=f"{completed} completed")
        s2.metric("Artifacts", len(artifacts))
        s3.metric("Documents", len(docs))
        s4.metric("Created", expert["created_at"][:10])

        st.divider()

        # Edit form
        with st.form(f"edit_expert_{expert['id']}"):
            ec1, ec2 = st.columns(2)
            new_name = ec1.text_input("Name", value=expert["name"])
            new_role = ec2.text_input("Role", value=expert["role"])
            ec3, ec4 = st.columns(2)
            new_dept = ec3.text_input("Department", value=expert["department"])
            _ = ec4.empty()
            new_notes = st.text_area("Notes", value=expert["notes"], height=80)
            col_save, col_del, _ = st.columns([1, 1, 4])
            save = col_save.form_submit_button("💾 Save Changes", type="primary")
            delete = col_del.form_submit_button("🗑️ Delete Expert", type="secondary")

            if save:
                db.update_expert(expert["id"], new_name, new_role, new_dept, new_notes)
                st.success("Saved.")
                st.rerun()

            if delete:
                db.delete_expert(expert["id"])
                st.warning(f"Expert **{expert['name']}** and all their data deleted.")
                st.rerun()

        # Recent sessions
        if sessions:
            st.caption("**Recent Sessions:**")
            for s in sessions[:3]:
                status_icon = "✅" if s["status"] == "completed" else "🔵"
                st.caption(
                    f"{status_icon} Session #{s['id']} — started {s['started_at'][:10]}"
                    + (f", completed {s['completed_at'][:10]}" if s["completed_at"] else "")
                )
