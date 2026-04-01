"""Page 5 — Expert Profile Management."""
import streamlit as st

from mindvault.database import sqlite_db as db

st.set_page_config(page_title="Experts · MindVault", layout="wide")
db.init_db()

st.title("Expert Profiles")
st.caption("Create and manage the subject-matter experts whose knowledge is being preserved.")

# ── Create new expert ─────────────────────────────────────────────────────────
with st.expander("Create New Expert", expanded=not bool(db.get_experts())):
    with st.form("create_expert_form"):
        c1, c2 = st.columns(2)
        name = c1.text_input("Full Name *", placeholder="Jane Smith")
        role = c2.text_input("Role / Title *", placeholder="Principal Engineer")
        c3, c4 = st.columns(2)
        department = c3.text_input("Department", placeholder="Platform Engineering")
        domain = c4.text_input("Knowledge Domain", placeholder="Cloud Infrastructure, Data Pipelines…")
        c5, c6 = st.columns(2)
        tenure_years = c5.number_input("Tenure (years)", min_value=0, max_value=60, value=0, step=1)
        departure_urgency = c6.selectbox(
            "Departure Urgency",
            options=["standard", "high", "critical"],
            index=0,
        )
        key_projects = st.text_area(
            "Key Projects",
            placeholder="List the major projects this expert has led or contributed to…",
            height=68,
        )
        knowledge_gaps = st.text_area(
            "Known Knowledge Gaps to Fill",
            placeholder="What does the organisation need to learn from this expert that isn't documented?",
            height=68,
        )
        notes = st.text_area("Notes", placeholder="Any other context, constraints, or background…", height=68)
        submitted = st.form_submit_button("Create Expert", type="primary")
        if submitted:
            if not name.strip() or not role.strip():
                st.error("Name and Role are required.")
            elif any(e["name"].strip().lower() == name.strip().lower() for e in db.get_experts()):
                st.error(f"An expert named '{name.strip()}' already exists. Use a different name or edit the existing profile.")
            else:
                db.create_expert(
                    name=name.strip(),
                    role=role.strip(),
                    department=department.strip(),
                    notes=notes.strip(),
                    domain=domain.strip(),
                    tenure_years=int(tenure_years),
                    key_projects=key_projects.strip(),
                    knowledge_gaps=knowledge_gaps.strip(),
                    departure_urgency=departure_urgency,
                )
                st.toast(f"Expert '{name.strip()}' created.", icon="✅")
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
            new_dept = ec3.text_input("Department", value=expert.get("department", ""))
            new_domain = ec4.text_input("Knowledge Domain", value=expert.get("domain", ""))
            ec5, ec6 = st.columns(2)
            new_tenure = ec5.number_input(
                "Tenure (years)", min_value=0, max_value=60,
                value=int(expert.get("tenure_years") or 0), step=1,
            )
            urgency_options = ["standard", "high", "critical"]
            current_urgency = expert.get("departure_urgency") or "standard"
            if current_urgency not in urgency_options:
                current_urgency = "standard"
            new_urgency = ec6.selectbox(
                "Departure Urgency",
                options=urgency_options,
                index=urgency_options.index(current_urgency),
                key=f"urgency_{expert['id']}",
            )
            new_key_projects = st.text_area(
                "Key Projects", value=expert.get("key_projects", ""), height=68,
            )
            new_knowledge_gaps = st.text_area(
                "Known Knowledge Gaps", value=expert.get("knowledge_gaps", ""), height=68,
            )
            new_notes = st.text_area("Notes", value=expert.get("notes", ""), height=68)
            col_save, col_del, _ = st.columns([1, 1, 4])
            save = col_save.form_submit_button("Save Changes", type="primary")
            delete = col_del.form_submit_button("Delete Expert", type="secondary")

            if save:
                db.update_expert(
                    expert_id=expert["id"],
                    name=new_name,
                    role=new_role,
                    department=new_dept,
                    notes=new_notes,
                    domain=new_domain,
                    tenure_years=int(new_tenure),
                    key_projects=new_key_projects,
                    knowledge_gaps=new_knowledge_gaps,
                    departure_urgency=new_urgency,
                )
                st.toast("Changes saved.", icon="✅")
                st.rerun()

            if delete:
                db.delete_expert(expert["id"])
                st.toast(f"Expert '{expert['name']}' deleted.", icon="🗑️")
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

st.divider()
st.caption("© 2026 Kiran Gade (KG). All rights reserved.")
