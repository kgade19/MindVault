# MindVault 🧠

**Knowledge Preservation Platform** — capture tacit expertise from departing subject-matter experts via AI-guided interviews, ingest their documents, extract structured knowledge artifacts, and make everything queryable by successors.

---

## Features

| Feature | Detail |
|---|---|
| 🎙️ AI Interviews | Claude conducts adaptive interviews, probing for decisions, lessons, processes, entities, and open questions. Mid-interview extraction fires every 3 turns. |
| 📥 Multi-Source Ingestion | PDF, web URL, plain text/markdown, images (Claude Vision), audio/video (Whisper STT) |
| 🗂️ Structured Artifacts | 5 artifact types: `decision`, `lesson_learned`, `process`, `named_entity`, `open_question` |
| 🔍 RAG Query | Semantic search over ChromaDB, Claude synthesis with citations and conflict detection |
| 🔊 Voice I/O | Optional toggle: faster-whisper STT input, gTTS TTS playback |
| 🧩 Gap Analysis | Claude identifies knowledge gaps in ingested documents and generates interview questions |
| 🔒 SHA-256 Dedup | Duplicate document detection at ingestion time |
| 📤 Export | JSON and Markdown export from the Artifacts browser |

---

## Requirements

- Python 3.11+
- An [Anthropic API key](https://console.anthropic.com/)
- Internet access for gTTS (text-to-speech via Google's free endpoint)
- `ffmpeg` on PATH for audio transcription (optional — only needed for non-WAV audio)

---

## Setup

### 1. Clone & enter the project

```bash
cd C:\Users\gadek\source\repos\mindvault
```

### 2. Create a virtual environment

```bash
python -m venv .venv
.venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

```bash
copy .env.example .env
```

Edit `.env` and set your `ANTHROPIC_API_KEY`:

```
ANTHROPIC_API_KEY=sk-ant-...
```

Optional variables (defaults are fine to start):

| Variable | Default | Description |
|---|---|---|
| `CLAUDE_MODEL` | `claude-3-5-sonnet-20241022` | Anthropic model ID |
| `WHISPER_MODEL_SIZE` | `base` | faster-whisper model size (`tiny`, `base`, `small`, `medium`, `large-v2`) |
| `EXTRACTION_INTERVAL` | `3` | Mid-interview extraction frequency (every N user turns) |
| `DATA_DIR` | `data` | Root for SQLite DB, ChromaDB, and uploads |

### 5. Run

```bash
streamlit run app.py
```

The app opens at `http://localhost:8501`.

---

## First Run Walkthrough

1. **Create an Expert** — go to 👤 Experts and add the departing SME's name, role, and department.
2. **Start an Interview** — go to 🎙️ Interview, select the expert, click **▶ Start New Session**. Claude will open with the first question.
3. **Answer conversationally** — type (or speak with Voice I/O toggled on). Claude probes adaptively. Artifacts are extracted every 3 turns automatically.
4. **Complete the Interview** — click **✅ Complete Interview** for a final extraction pass.
5. **Ingest documents** — go to 📥 Ingest and upload any PDFs, paste URLs, or upload audio recordings. Each source is chunked, embedded, and extracted.
6. **Query** — go to 🔍 Query, ask a question. Get a cited answer with any detected conflicts flagged.
7. **Browse** — go to 🗂️ Artifacts to filter, search, and export all captured knowledge.

---

## Project Structure

```
mindvault/
├── app.py                    # Home dashboard
├── requirements.txt
├── .env.example
├── pages/
│   ├── 1_Interview.py
│   ├── 2_Ingest.py
│   ├── 3_Query.py
│   ├── 4_Artifacts.py
│   └── 5_Experts.py
├── mindvault/
│   ├── config.py
│   ├── database/             # SQLite + ChromaDB
│   ├── llm/                  # Claude client, interview agent, extractor
│   ├── ingestion/            # PDF, URL, image, audio
│   ├── voice/                # STT (Whisper) + TTS (gTTS)
│   └── rag/                  # Embedder + retriever
├── prompts/                  # Plain-text system prompts (live-reload)
│   ├── interview_system.txt
│   ├── extraction_system.txt
│   ├── query_system.txt
│   └── resource_analysis.txt
└── data/                     # Runtime data (gitignored)
    ├── mindvault.db
    ├── chroma/
    └── uploads/
```

---

## Customising Prompts

All LLM system prompts are in `prompts/` as plain text files. Edit them and restart Streamlit — no code changes needed. Key slots:

- `interview_system.txt` — `{expert_name}`, `{expert_role}`, `{expert_department}`, `{turn_count}`

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `ANTHROPIC_API_KEY` not set error | Copy `.env.example` to `.env` and add your key |
| Whisper model downloads slowly on first run | This is normal — the model is cached after first use |
| Audio transcription fails | Install `ffmpeg` and add it to your PATH |
| ChromaDB error on startup | Delete `data/chroma/` and let it rebuild |
| gTTS timeout | Requires internet access; TTS is silently skipped if offline |
