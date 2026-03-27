"""Page 1 — Expert Interview."""
import streamlit as st

from mindvault.config import EXTRACTION_INTERVAL
from mindvault.database import sqlite_db as db
from mindvault.llm import extractor, interview_agent
from mindvault.llm.claude_client import stream_chat
from mindvault.rag import embedder
from mindvault.voice.stt import transcribe
from mindvault.voice.tts import synthesize

st.set_page_config(page_title="Interview · MindVault", page_icon="🧠", layout="wide")

init_db = db.init_db
init_db()

# ── Sidebar: expert + session controls ───────────────────────────────────────
st.sidebar.title("🎙️ Interview")

experts = db.get_experts()
if not experts:
    st.warning("No experts found. Please create an expert on the 👤 Experts page first.")
    st.stop()

expert_options = {f"{e['name']} ({e['role']})": e for e in experts}
selected_label = st.sidebar.selectbox("Select Expert", list(expert_options.keys()))
expert = expert_options[selected_label]

# Voice toggle
voice_enabled = st.sidebar.toggle("🔊 Voice I/O", value=False, help="Enable STT microphone input and TTS playback")

st.sidebar.divider()

# Session management
active_session = db.get_active_session(expert["id"])

if active_session:
    st.sidebar.success(f"Active session #{active_session['id']}")
    if st.sidebar.button("✅ Complete Interview", type="primary"):
        db.complete_session(active_session["id"])
        _msgs = db.get_messages(active_session["id"])
        full_text = "\n\n".join(f"{m['role'].upper()}: {m['content']}" for m in _msgs)
        with st.spinner("Extracting final knowledge artifacts…"):
            artifacts = extractor.extract_artifacts(full_text)
            for art in artifacts:
                art_id = db.create_artifact(
                    artifact_type=art["artifact_type"],
                    title=art["title"],
                    content=art["content"],
                    tags=art.get("tags", []),
                    expert_id=expert["id"],
                    session_id=active_session["id"],
                )
                embedder.embed_artifact(
                    art_id, art["title"], art["content"],
                    art["artifact_type"], expert["id"]
                )
        st.sidebar.success(f"Interview completed! {len(artifacts)} artifacts saved.")
        st.rerun()

    if st.sidebar.button("🗑️ Abandon Session", type="secondary"):
        db.complete_session(active_session["id"])
        st.rerun()
else:
    if st.sidebar.button("▶ Start New Session", type="primary"):
        new_id = db.create_session(expert["id"])
        opening = interview_agent.get_opening_message(expert)
        db.append_message(new_id, "assistant", opening)
        st.rerun()

# ── Main area ─────────────────────────────────────────────────────────────────
st.title(f"🎙️ Interview: {expert['name']}")
st.caption(f"{expert['role']} · {expert['department']}")

if not active_session:
    st.info("No active session. Click **▶ Start New Session** in the sidebar to begin.")
    st.stop()

session_id = active_session["id"]
messages = db.get_messages(session_id)
turn_count = len([m for m in messages if m["role"] == "user"])

# Extraction badge
col_t, col_b = st.columns([4, 1])
with col_t:
    st.caption(f"Session #{session_id} · {len(messages)} messages · {turn_count} user turns")
with col_b:
    next_extract = EXTRACTION_INTERVAL - (turn_count % EXTRACTION_INTERVAL) if turn_count % EXTRACTION_INTERVAL != 0 else EXTRACTION_INTERVAL
    st.caption(f"Next mid-extraction in {next_extract} turn(s)")

# Render conversation
for msg in messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ── Voice STT input ───────────────────────────────────────────────────────────
user_input: str | None = None

if voice_enabled:
    st.subheader("🎤 Voice Input")
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

    # Build context
    all_messages = db.get_messages(session_id)
    system_prompt = interview_agent.build_system_prompt(expert, turn_count)
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

    # Mid-interview extraction
    if interview_agent.should_extract(turn_count):
        all_msg_text = "\n\n".join(
            f"{m['role'].upper()}: {m['content']}"
            for m in db.get_messages(session_id)
        )
        with st.spinner(f"🔍 Mid-interview extraction at turn {turn_count}…"):
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
                )
                embedder.embed_artifact(
                    art_id, art["title"], art["content"],
                    art["artifact_type"], expert["id"]
                )
                saved += 1
        if saved:
            st.toast(f"🗂️ {saved} artifact(s) extracted at turn {turn_count}", icon="✅")

    st.rerun()
