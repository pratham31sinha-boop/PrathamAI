# Pratham AI: Full-Production Architecture & Workspace Environment
Pratham AI is an advanced, production-grade conversational engine and development ecosystem built using an asymmetric Flask backend architecture and an ultra-lean, Claude-inspired Single Page Application (SPA) frontend.
Engineered to operate as a general-purpose digital assistant, code interpreter, and automated workspace agent, Pratham AI bridges state-of-the-art LLMs with a sandboxed server-side operating runtime. The platform features native code execution loops, sophisticated multi-engine state failovers, automated source tracking via GitHub persistence mirrors, document generation nodes, and granular workspace management modules.
## 🏛️ Architectural Overview
```
                      +---------------------------------------+
                      |        Pratham AI SPA Frontend        |
                      |   (Claude-Aesthetic Tailwind Engine)  |
                      +-------------------+-------+-----------+
                                          |       ^
                Auth token exchange / SSE |       | Streams image URLs, files,
                Stream payload requests   |       | terminal events, and tokens
                                          v       |
                      +---------------------------+-----------+
                      |          Flask Application Core       |
                      |          (Asynchronous Control)       |
                      +---+-------------------+-----------+---+
                          |                   |           |
    Persistent Metadata   |                   |           | File logging & Library read
    & Storage Sync        v                   v           v
  +-----------------------+--+   +------------+--+   +----+--------------------+
  |      Supabase Layer      |   | Background |   |  GitHub Data Repository |
  | (Convo state fallbacks)  |   | Terminal   |   | (public_data.txt, logs, |
  +--------------------------+   | Workspace  |   |  education reference)   |
                                 +------------+   +-------------------------+

```
### 1. Unified Control Layer (app.py)
The server acts as a low-latency gateway orchestrating authentication states, managing multi-tier API rotation cooldowns, handling sandboxed code block runtime cycles, and compiling custom document assets down to byte-level structures.
### 2. Contextual Frontend Interface (index.html)
A premium, highly responsive user interface designed with Tailwind CSS that maximizes screen scannability. It features complex text selection handling, synchronous terminal event logging frames, an interactive file registry explorer dashboard, real-time token rendering pipelines, and an expansive artifact preview system capable of running live frontend sandboxes.
## ⚡ Core Enterprise Feature Suite
| Capability | Technical Realization | Performance Impact |
|---|---|---|
| **Real Background Terminal** | Server-side subprocess loop intercepting python/bash fenced sequences on the fly. Interlaced execution returns data to the model frame instantly. | Transforms the LLM from a simulator into an active runtime operator. |
| **Multi-Engine Failover** | Automatic fallback tracking across **Groq**, **OpenRouter**, **Cerebras**, and **Mistral Large** APIs with distinct cooling mechanisms. | Insulates production spaces from targeted rate limits and vendor outages. |
| **Hybrid Storage Strategy** | Primary relational indexing via Supabase coupled with continuous transaction logging to a dedicated GitHub repo. Local in-memory dictionary fallbacks protect uptime. | Zero-loss message record preservation with high-availability local storage structures. |
| **Byte-Level Document Node** | Native low-overhead .zip generation and an embedded structural .pdf layout engine built right into the Python source. | Eradicates server dependencies on external heavy engines like pandoc or print daemons. |
| **Deep Ingest Diagnostics** | Dynamic text extractors (PyMuPDF, pdfplumber, pypdf) combined with raw, byte-level structural metadata sniffing for standard files and images. | Gives the agent deep technical intuition regarding uploaded media layouts and properties. |
## 🔍 Technical Deep Dive
### The Sandboxed Terminal Execution Cycle
When a user submits a prompt demanding data processing, script evaluation, or layout construction, Pratham AI avoids simple static text outputs. It launches an active internal lifecycle:
```
[ User Prompt ] ---> [ Model Output Stream ] ---> [ Intercept Executable Block ]
                                                                |
+---------------------------------------------------------------+
|
v
[ Generate Secure Temp Scratch Directory ]
|
v
[ Spawn Isolation Subprocess (Python/Bash Context) ]
|
v
[ Capture Output Streams up to 200,000 Chars ]
|
v
[ Append Return Code / Diagnostics into LLM Core Buffer ] ---> [ Iterative Continue Pass ]

```
This cycle permits up to **4 consecutive runtime passes** per user turn. The model reads its own real-world outputs, evaluates script crashes, updates configuration profiles via localized patches, and ensures a functioning solution is generated before finalizing the message stream.
### Advanced File Synchronization Framework
To minimize high-frequency HTTP round-trip lag when writing or tracking conversation objects back to GitHub, the platform utilizes an intelligent cache manager:
 * **SHA Metadata Cache (_gh_sha_cache)**: Holds targeted file signatures for up to **8 seconds**. This prevents secondary lookups during rapid text updates.
 * **Smart Content Refiner (_strip_export_filler)**: Employs structural regex components to scrub common chatbot preambles and chat fillers from deliverable codes automatically.
 * **Atomic Search/Replace Protocol**: Parses editfile:<filename> modules containing precise alignment tags:
   ```text
   <<<<<<< SEARCH
   [verbatim target string pattern]
   =======
   [updated implementation state]
   >>>>>>> REPLACE
   
   ```
   This strategy applies atomic modifications to specific lines inside large files rather than rewriting the entire source block, drastically cutting processing times.
## ⚙️ Deployment & Environment Configuration
### Prerequisites
Ensure your host machine features **Python 3.8+** along with standard build utilities. To leverage the platform's advanced text extraction workflows, include these additional workspace hooks:
```bash
pip install flask flask-cors pypdf pdfplumber pymupdf

```
### Required Variables Configuration
Configure the following keys in your host system's configuration file or environment space:
```env
# Multi-Engine Token Infrastructure (Comma-Separated Array Support)
GROQ_API_KEY="gsk_prod_primary_key_here,gsk_backup_key_rotation_here"
GROQ_API_KEY_2="gsk_additional_failover_layer_key"
OPENROUTER_API_KEY="sk-or-v1-..."
CEREBRAS_API_KEY="csk-..."
MISTRAL_API_KEY="..."

# Secure Version Control Mirror Setup
GITHUB_TOKEN="ghp_secure_repository_scope_access_token_here"
GITHUB_REPO="your-github-username/your-data-repo-name"

# Relational Layer Engine
SUPABASE_URL="https://your-project-id.supabase.co"
SUPABASE_SERVICE_KEY="eyJhbGciOi..."

# Authentication Security Profiles
VIP_SECRET_CODE="31082011"
SESSION_SECRET="generate-a-high-entropy-cryptographic-hash-here"
SESSION_TOKEN_TTL_DAYS="30"

```
## 🛠️ Direct API Interface Mapping
### POST /api/chat-stream
Initiates a low-latency Server-Sent Events (SSE) stream processing the full context engine history.
 * **Headers**: Authorization: Bearer <JWT_Token_Or_Google_Id>
 * **Payload Structure**:
   ```json
   {
     "message": "Write a clean index.html showing a particle network animation. Make it a zip.",
     "conversation_id": "optional-uuid-string-here"
   }
   
   ```
 * **Event Dispatch Structure**:
   * type: metadata — Returns the verified conversation_id string for state tracking.
   * type: token — Delivers incremental content tokens straight to the screen.
   * type: terminal_output — Emits active diagnostic updates detailing script executions.
   * type: file_ready — Passes back secure link objects pointing to completed file resources.
   * type: image — Delivers live generation hooks tied to the Pollinations AI processor.
   * type: complete — Signals that execution frames have wrapped up for this turn.
### POST /api/upload
Ingests dynamic files directly into the platform's analysis pipeline.
 * **Payload Type**: multipart/form-data (Key name: file)
 * **Behavior Matrix**:
   * **.pdf / .docx** -> Triggers deep textual extraction maps, returning searchable layouts to the model.
   * **.png / .jpg / .gif** -> Fires up localized script hooks to read internal EXIF tags, dimensions, channels, color profiles, and chunk arrays.
   * **.json / .csv / .txt** -> Returns raw text chunks up to the configured validation ceiling.
## 💡 Prompt Structure & Workspace Conventions
Pratham AI responds directly to embedded functional tags inside your chat prompts. You can inject these keywords to shape context processing manually:
 * **@web**: Explicitly forces the system to run real-time search passes via DuckDuckGo, pulling live details into the prompt context before generating answers.
 * **@education**: Restricts the system prompt logic, scoping the agent's attention directly to reading reference textbooks and materials found within data/education/.
 * **/remember [content]** or **add this to your memory: [content]**: Commands the engine to dynamically update data/public_data.txt in the GitHub repo. This saves facts, rules, or user preferences globally across all future chat sessions.
 * **[diagnostic status / health check]**: (Available for authenticated system creators) Prompts the backend to run an internal sanity check. It runs test scripts, evaluates terminal permissions, checks folder access, and details the performance status of all connected services.
