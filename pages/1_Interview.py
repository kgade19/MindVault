"""Page 1 — Expert Interview."""
import hashlib
import streamlit as st

from mindvault.config import EXTRACTION_INTERVAL
from mindvault.database import sqlite_db as db
from mindvault.ingestion.audio_ingester import transcribe as transcribe_audio
from mindvault.ingestion.image_ingester import ingest_image
from mindvault.ingestion.pdf_parser import extract_text as extract_pdf_text
from mindvault.ingestion.pipeline import run_pipeline
from mindvault.ingestion.url_fetcher import fetch_url
from mindvault.llm import extractor, interview_agent
from mindvault.llm.consistency_checker import run_for_expert as run_consistency_check
from mindvault.llm.extractor import get_low_confidence_mental_models
from mindvault.llm.claude_client import stream_chat
from mindvault.rag import embedder
from mindvault.voice.stt import transcribe
from mindvault.voice.tts import synthesize

st.set_page_config(page_title="Interview · MindVault", layout="wide")

db.init_db()

# ── Session state defaults ────────────────────────────────────────────────────
# reprobe_instruction is rebuilt from low-confidence artifacts after each
# mid-interview extraction and injected into the next turn's system prompt.
st.session_state.setdefault("reprobe_instruction", "")
st.session_state.setdefault("previous_summary", "")
st.session_state.setdefault("_current_expert_id", None)

# ── Sidebar: expert + session controls ───────────────────────────────────────
st.sidebar.title("Interview")

experts = db.get_experts()
if not experts:
    st.warning("No experts found. Please create an expert on the Experts page first.")
    st.stop()

expert_options = {f"{e['name']} ({e['role']})": e for e in experts}
selected_label = st.sidebar.selectbox("Select Expert", list(expert_options.keys()))
expert = expert_options[selected_label]

# Clear per-expert session state when switching experts so stale reprobe
# instructions do not bleed into a new expert's session.
if st.session_state["_current_expert_id"] != expert["id"]:
    st.session_state["reprobe_instruction"] = ""
    st.session_state["previous_summary"] = ""
    st.session_state["_current_expert_id"] = expert["id"]

# Voice toggle
voice_enabled = st.sidebar.toggle("Voice I/O", value=False, help="Enable STT microphone input and TTS playback")

st.sidebar.divider()

# Session management
active_session = db.get_active_session(expert["id"])

if active_session:
    st.sidebar.success(f"Active session #{active_session['id']}")

    if st.sidebar.button("Complete Interview", type="primary"):
        # Run full extraction + embed BEFORE marking complete so no conversation
        # content is ever silently discarded.
        _msgs = db.get_messages(active_session["id"])
        full_text = "\n\n".join(f"{m['role'].upper()}: {m['content']}" for m in _msgs)
        with st.spinner("Extracting final knowledge artifacts…"):
            artifacts = extractor.extract_artifacts(full_text)
            saved = 0
            for art in artifacts:
                art_id = db.create_artifact(
                    artifact_type=art["artifact_type"],
                    title=art["title"],
                    content=art["content"],
                    tags=art.get("tags", []),
                    expert_id=expert["id"],
                    session_id=active_session["id"],
                    confidence=float(art.get("confidence", 1.0)),
                )
                embedder.embed_artifact(
                    art_id, art["title"], art["content"],
                    art["artifact_type"], expert["id"],
                )
                saved += 1
        db.complete_session(active_session["id"])
        # Run consistency check across all artifacts for this expert
        with st.spinner("Running consistency check…"):
            conflicts = run_consistency_check(expert["id"])
        st.session_state["reprobe_instruction"] = ""
        st.session_state["previous_summary"] = ""
        notice = f"Interview completed — {saved} artifact(s) saved."
        if conflicts:
            notice += f" {len(conflicts)} consistency issue(s) flagged."
        st.toast(notice, icon="✅")
        st.rerun()

    if st.sidebar.button("Abandon Session", type="secondary"):
        # Extract anything captured so far — abandoning should never lose content.
        _msgs = db.get_messages(active_session["id"])
        if _msgs:
            full_text = "\n\n".join(f"{m['role'].upper()}: {m['content']}" for m in _msgs)
            with st.spinner("Saving captured content before closing…"):
                artifacts = extractor.extract_artifacts(full_text)
                for art in artifacts:
                    art_id = db.create_artifact(
                        artifact_type=art["artifact_type"],
                        title=art["title"],
                        content=art["content"],
                        tags=art.get("tags", []),
                        expert_id=expert["id"],
                        session_id=active_session["id"],
                        confidence=float(art.get("confidence", 1.0)),
                    )
                    embedder.embed_artifact(
                        art_id, art["title"], art["content"],
                        art["artifact_type"], expert["id"],
                    )
        db.complete_session(active_session["id"])
        st.session_state["reprobe_instruction"] = ""
        st.session_state["previous_summary"] = ""
        st.toast("Session closed. Captured content saved.", icon="📁")
        st.rerun()

    # ── Mid-session resource upload ───────────────────────────────────────────
    # The expert can share supporting material at any point; chunks are embedded
    # immediately so the next turn picks them up via per-turn RAG retrieval.
    st.sidebar.divider()
    with st.sidebar.expander("Add a Resource", expanded=False):
        st.caption("Upload a file or paste a URL — the interviewer will draw on it from the next turn.")
        mid_file = st.file_uploader(
            "File",
            type=["pdf", "txt", "png", "jpg", "jpeg", "webp", "mp3", "wav", "m4a", "mp4"],
            key=f"mid_upload_{active_session['id']}",
        )
        mid_url = st.text_input("Or paste a URL", placeholder="https://…", key=f"mid_url_{active_session['id']}")

        if st.button("Add Resource", type="primary", key=f"btn_mid_{active_session['id']}"):
            session_project = active_session.get("topic", "")
            result = None

            if mid_file:
                file_bytes = mid_file.read()
                sha256 = hashlib.sha256(file_bytes).hexdigest()
                fname = mid_file.name
                ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""

                with st.spinner(f"Processing {fname}…"):
                    try:
                        if ext == "pdf":
                            content = extract_pdf_text(file_bytes)
                            stype = "pdf"
                        elif ext in ("png", "jpg", "jpeg", "webp"):
                            content = ingest_image(file_bytes, filename=fname)
                            stype = "image"
                        elif ext in ("mp3", "wav", "m4a", "mp4"):
                            content = transcribe_audio(file_bytes)
                            stype = "audio"
                        else:
                            content = file_bytes.decode("utf-8", errors="replace")
                            stype = "text"

                        if content.strip():
                            result = run_pipeline(
                                expert_id=expert["id"],
                                source_type=stype,
                                source_ref=fname,
                                title=fname,
                                content_text=content,
                                sha256=sha256,
                                project=session_project,
                            )
                        else:
                            st.warning("Could not extract content from this file.")
                    except Exception as exc:
                        st.error(f"Failed to process file: {exc}")

            elif mid_url.strip():
                with st.spinner(f"Fetching {mid_url.strip()}…"):
                    try:
                        title, content = fetch_url(mid_url.strip())
                        sha256 = hashlib.sha256(content.encode()).hexdigest()
                        result = run_pipeline(
                            expert_id=expert["id"],
                            source_type="url",
                            source_ref=mid_url.strip(),
                            title=title,
                            content_text=content,
                            sha256=sha256,
                            project=session_project,
                        )
                    except Exception as exc:
                        st.error(f"Failed to fetch URL: {exc}")
            else:
                st.warning("Please provide a file or URL.")

            if result:
                if result["skipped"]:
                    st.info(f"Already ingested as \"{result['existing']['title']}\" — skipping.")
                else:
                    st.toast(
                        f"Resource added ({result['n_chunks']} chunk(s)) — "
                        "the interviewer will reference it from the next turn.",
                        icon="📎",
                    )

else:
    # No active session — show start controls.

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
    prior_sessions = db.get_sessions_for_expert(expert["id"])
    # Topics from completed sessions for this expert — used to label already-covered projects.
    covered_topics = {
        s["topic"] for s in prior_sessions
        if s.get("topic") and s.get("status") == "completed"
    }
    prior_completed = [s for s in prior_sessions if s.get("status") == "completed"]

    if key_projects:
        # Build labelled options: mark already-covered projects so user can prioritise uncovered ones.
        project_options = []
        for p in key_projects:
            label = f"{p}  \u2713 covered" if p in covered_topics else p
            project_options.append((label, p))
        project_options.append(("General / Other", ""))

        selected_label = st.sidebar.selectbox(
            "Session Project",
            [label for label, _ in project_options],
        )
        resolved_topic = next(val for label, val in project_options if label == selected_label)

        if selected_label == "General / Other":
            custom = st.sidebar.text_input("Custom topic", placeholder="optional — leave blank for open session")
            resolved_topic = custom.strip()
    else:
        resolved_topic = st.sidebar.text_input(
            "Session Topic",
            placeholder="e.g. Deployment pipeline, Vendor relationships…",
        ).strip()

    if prior_completed:
        continuation = st.sidebar.radio(
            "Session mode",
            options=["Start fresh", "Continue from previous"],
            index=0,
        )
    else:
        continuation = "Start fresh"

    if st.sidebar.button("Start Session", type="primary"):
        summary = ""
        if continuation == "Continue from previous":
            with st.spinner("Summarising previous session…"):
                summary = interview_agent.get_session_summary(expert["id"])
        new_id = db.create_session(expert["id"], topic=resolved_topic)
        opening = interview_agent.get_opening_message(expert, session_topic=resolved_topic)
        db.append_message(new_id, "assistant", opening)
        st.session_state["previous_summary"] = summary
        st.session_state["reprobe_instruction"] = ""
        st.rerun()

# ── Main area ─────────────────────────────────────────────────────────────────
st.title(f"Interview: {expert['name']}")
st.caption(f"{expert['role']} · {expert['department']}")

if not active_session:
    st.info("No active session. Click **Start Session** in the sidebar to begin.")
    st.stop()

session_id = active_session["id"]
messages = db.get_messages(session_id)
turn_count = len([m for m in messages if m["role"] == "user"])

# Session info bar
col_t, col_b = st.columns([4, 1])
with col_t:
    topic_label = f" · {active_session.get('topic')}" if active_session.get("topic") else ""
    st.caption(f"Session #{session_id}{topic_label} · {len(messages)} messages · {turn_count} user turns")
with col_b:
    next_extract = (
        EXTRACTION_INTERVAL - (turn_count % EXTRACTION_INTERVAL)
        if turn_count % EXTRACTION_INTERVAL != 0
        else EXTRACTION_INTERVAL
    )
    st.caption(f"Next extraction in {next_extract} turn(s)")

# Re-probe badge — visible when low-confidence topics are queued for follow-up
if st.session_state.get("reprobe_instruction"):
    st.info("Low-confidence topic(s) detected — the interviewer will probe for more detail.")

# Render conversation history
for msg in messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ── Voice STT input ───────────────────────────────────────────────────────────
user_input: str | None = None

if voice_enabled:
    st.subheader("Voice Input")
    audio_data = st.audio_input("Record your response", key=f"stt_{session_id}_{turn_count}")
    if audio_data is not None:
        with st.spinner("Transcribing…"):
            user_input = transcribe(audio_data.getvalue())
        if user_input:
            st.info(f"Transcribed: {user_input}")

# Text input (always available)
text_input = st.chat_input("Type your response…")
if text_input:
    user_input = text_input

# ── Process user turn ─────────────────────────────────────────────────────────
if user_input:
    db.append_message(session_id, "user", user_input)
    turn_count += 1

    with st.chat_message("user"):
        st.markdown(user_input)

    system_prompt = interview_agent.build_system_prompt(
        expert,
        turn_count,
        previous_summary=st.session_state.get("previous_summary", ""),
        reprobe_instruction=st.session_state.get("reprobe_instruction", ""),
        session_topic=active_session.get("topic", ""),
        document_context=interview_agent.get_document_context(
            expert["id"],
            user_input,
            session_topic=active_session.get("topic", ""),
        ),
    )
    claude_messages = interview_agent.build_messages(session_id)

    # Stream the assistant response token-by-token
    with st.chat_message("assistant"):
        placeholder = st.empty()
        full_response = ""
        for delta in stream_chat(claude_messages, system=system_prompt, max_tokens=1024):
            full_response += delta
            placeholder.markdown(full_response + "▌")
        placeholder.markdown(full_response)

    db.append_message(session_id, "assistant", full_response)

    # TTS playback
    if voice_enabled and full_response:
        audio_buf = synthesize(full_response)
        st.audio(audio_buf, format="audio/mp3", autoplay=True)

    # Mid-interview extraction — fires every EXTRACTION_INTERVAL user turns
    if interview_agent.should_extract(turn_count):
        all_msg_text = "\n\n".join(
            f"{m['role'].upper()}: {m['content']}"
            for m in db.get_messages(session_id)
        )
        with st.spinner(f"Mid-interview extraction at turn {turn_count}…"):
            artifacts = extractor.extract_artifacts(all_msg_text)
            saved = 0
            for art in artifacts:
                art_id = db.create_artifact(
                    artifact_type=art["artifact_type"],
                    title=art["title"],
                    content=art["content"],
                    tags=art.get("tags", []),
                    expert_id=expert["id"],
                    session_id=session_id,
                    confidence=float(art.get("confidence", 1.0)),
                )
                embedder.embed_artifact(
                    art_id, art["title"], art["content"],
                    art["artifact_type"], expert["id"],
                )
                saved += 1

        # Update the reprobe instruction for the NEXT turn based on what came back
        st.session_state["reprobe_instruction"] = (
            interview_agent._build_reprobe_instruction(artifacts)
        )

        if saved:
            st.toast(f"{saved} artifact(s) extracted at turn {turn_count}")

    st.rerun()

st.divider()
st.caption("© 2026 Kiran Gade (KG). All rights reserved.")

