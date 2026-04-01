# MindVault

**Knowledge Preservation Platform** — capture tacit expertise from departing subject-matter experts via AI-guided interviews, ingest their documents, extract structured knowledge artifacts, and make everything queryable by successors.

---

## Features

| Feature | Detail |
|---|---|
| AI Interviews | Claude conducts adaptive 4-phase interviews, probing decisions, processes, heuristics, and mental models. Mid-interview extraction fires every 3 turns; low-confidence `mental_model` artifacts trigger automatic re-probe on the next turn. |
| Multi-Source Ingestion | PDF, web URL, plain text/markdown, images (Claude Vision), audio/video (Whisper/Groq STT) |
| Structured Artifacts | 7 artifact types: `heuristic`, `if_then_rule`, `case_example`, `red_flag`, `mental_model`, `exception`, `decision_factor`. Each artifact carries a `confidence` score (0.0-1.0) set by the LLM at extraction time. |
| Post-Session Consistency Check | After every completed session the consistency checker scans all of an expert's artifacts for contradictions and stores results in `artifact_conflicts`. |
| RAG Query | Semantic search over both ChromaDB collections with Claude synthesis, citations, and conflict detection. |
| Voice I/O | Optional toggle: Groq cloud STT (default) or local faster-whisper STT input; gTTS TTS playback. |
| Document Gap Analysis | Claude identifies knowledge gaps in ingested documents and generates targeted interview questions. |
| Expert Profiles | Rich expert metadata: domain, tenure years, key projects, knowledge gaps, and departure urgency. |
| SHA-256 Dedup | Duplicate document detection at ingestion time. |
| Export | JSON and Markdown export from the Artifacts browser. |

---

## Requirements

- Python 3.11+
- An [Anthropic API key](https://console.anthropic.com/)
- A [Groq API key](https://console.groq.com/) (free) — required for the default Groq STT provider
- Internet access for gTTS (text-to-speech via Google's free endpoint)
- `ffmpeg` on PATH only if using `STT_PROVIDER=faster_whisper` for local audio transcription

---

## Setup

### 1. Clone and enter the project

`bash
cd mindvault
`

### 2. Create a virtual environment

`bash
python -m venv .venv
.venv\Scripts\activate       # Windows
source .venv/bin/activate    # macOS / Linux
`

### 3. Install dependencies

`bash
pip install -r requirements.txt
`

### 4. Configure environment variables

`bash
copy .env.example .env       # Windows
cp .env.example .env         # macOS / Linux
`

Edit `.env` and set at minimum:

`
ANTHROPIC_API_KEY=sk-ant-...
GROQ_API_KEY=gsk_...
`

Full list of supported variables:

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Required. Claude API key. Hard crash if missing. |
| `CLAUDE_MODEL` | `claude-3-5-sonnet-20241022` | Anthropic model ID |
| `STT_PROVIDER` | `groq` | `groq` (cloud, recommended) or `faster_whisper` (local, needs ffmpeg) |
| `GROQ_API_KEY` | — | Required when `STT_PROVIDER=groq`. Free at console.groq.com. |
| `WHISPER_MODEL_SIZE` | `base` | Only used when `STT_PROVIDER=faster_whisper`. Options: `tiny`, `base`, `small`, `medium`, `large-v2`. |
| `EXTRACTION_INTERVAL` | `3` | Mid-interview artifact extraction frequency (every N user turns) |
| `DATA_DIR` | `data` | Root directory for SQLite DB, ChromaDB, and uploads |

### 5. Run

`bash
streamlit run app.py
`

The app opens at `http://localhost:8501`.

---

## First Run Walkthrough

1. **Create an Expert** — go to Experts and add the departing SME's name, role, department, domain, tenure years, and key projects.
2. **Start an Interview** — go to Interview, select the expert, optionally set a session topic, and click Start New Session. Claude opens with the first question.
3. **Answer conversationally** — type (or speak with Voice I/O toggled on). Claude probes adaptively through four interview phases. Artifacts are extracted every 3 turns automatically, and low-confidence mental models trigger a follow-up re-probe.
4. **Complete the Interview** — click Complete Interview for a final extraction pass. The consistency checker then runs automatically across all the expert's artifacts.
5. **Ingest documents** — go to Ingest and upload PDFs, paste URLs, or upload audio recordings. Each source is parsed, chunked, embedded in ChromaDB, and extracted for artifacts. Claude identifies knowledge gaps and generates follow-up questions.
6. **Query** — go to Query, ask a question. Get a cited answer with any detected conflicts flagged.
7. **Browse** — go to Artifacts to filter, search, and export all captured knowledge as JSON or Markdown.

---

## Project Structure

`
mindvault/
├── app.py                          # Home dashboard
├── requirements.txt
├── .env.example
├── pages/
│   ├── 1_Interview.py              # AI interview + mid-session extraction
│   ├── 2_Ingest.py                 # Multi-source document ingestion
│   ├── 3_Query.py                  # RAG query with citations
│   ├── 4_Artifacts.py              # Artifact browser + export
│   └── 5_Experts.py                # Expert profile management
├── mindvault/
│   ├── config.py                   # All env vars, paths, load_prompt()
│   ├── database/
│   │   ├── sqlite_db.py            # Full schema DDL + all CRUD helpers
│   │   └── chroma_db.py            # ChromaDB wrapper (artifacts + resource_chunks)
│   ├── llm/
│   │   ├── claude_client.py        # All Claude calls (streaming, vision)
│   │   ├── interview_agent.py      # 4-phase prompt builder, re-probe logic
│   │   ├── extractor.py            # 7-type artifact extraction with confidence
│   │   └── consistency_checker.py  # Post-session artifact conflict detection
│   ├── ingestion/
│   │   ├── pipeline.py
│   │   ├── pdf_parser.py
│   │   ├── url_fetcher.py
│   │   ├── image_ingester.py
│   │   └── audio_ingester.py
│   ├── voice/
│   │   ├── stt.py                  # Groq cloud STT or faster-whisper local STT
│   │   └── tts.py                  # gTTS playback
│   └── rag/
│       ├── embedder.py             # Chunk (500w, 250w overlap) + ChromaDB upsert
│       └── retriever.py            # Query + synthesise + parse conflicts
├── prompts/                        # Plain-text system prompts (live-reload)
│   ├── interview_system.txt
│   ├── extraction_system.txt
│   ├── query_system.txt
│   ├── consistency_check.txt
│   └── resource_analysis.txt
└── data/                           # Runtime data (gitignored)
    ├── mindvault.db
    ├── chroma/
    └── uploads/
`

---

## Artifact Types

| Type | Description |
|---|---|
| `heuristic` | A reusable rule of thumb derived from the expert's experience |
| `if_then_rule` | Conditional logic: "IF X THEN Y" |
| `case_example` | A concrete narrative instance demonstrating a principle |
| `red_flag` | A warning signal with an escalation trigger: "when you see X, stop" |
| `mental_model` | How the expert frames or conceptualises a problem domain |
| `exception` | A known deviation from a rule: "applies except when..." |
| `decision_factor` | A recurring variable the expert always weighs before deciding |

Each artifact also carries a `confidence` float (0.0-1.0) assigned by Claude at extraction time. `mental_model` artifacts with confidence below 0.7 trigger a re-probe instruction injected into the next interview turn.

---

## Customising Prompts

All LLM system prompts are in `prompts/` as plain text files. Edit them and restart Streamlit — no code changes needed.

| File | Used by | Template slots |
|---|---|---|
| `interview_system.txt` | `interview_agent.py` | `{expert_name}`, `{expert_role}`, `{expert_department}`, `{turn_count}`, `{document_context}` |
| `extraction_system.txt` | `extractor.py` | — |
| `query_system.txt` | `retriever.py` | — |
| `consistency_check.txt` | `consistency_checker.py` | — |
| `resource_analysis.txt` | `extractor.py` | — |

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `ANTHROPIC_API_KEY` not set error | Copy `.env.example` to `.env` and add your key |
| Groq STT fails | Set `GROQ_API_KEY` in `.env`, or switch to `STT_PROVIDER=faster_whisper` |
| Whisper model downloads slowly on first local STT use | Normal — the model (~150 MB) is cached after first use |
| Audio transcription fails with faster-whisper | Install `ffmpeg` and add it to PATH |
| ChromaDB error on startup | Delete `data/chroma/` and let it rebuild |
| gTTS timeout | Requires internet access; TTS is silently skipped if offline |
| Windows Smart App Control blocks faster-whisper | Use the default Groq STT provider instead |

---

## License

© 2026 Kiran Gade (KG). All rights reserved.
