# Getting Started with HandoffScope

This guide provides a complete, step-by-step walkthrough to clone, configure, launch, and test the **HandoffScope** platform both with and without Docker.

---

## 📋 Prerequisites

Before starting, ensure you have the following installed on your machine:

| Component | Minimum Version | Required For |
|---|---|---|
| **Python** | 3.12+ | Backend FastAPI server & CLI scripts |
| **Node.js** | 18+ (20+ LTS recommended) | Frontend React + Vite development |
| **npm** | 9+ | Node package management |
| **Git** | 2.30+ | Source version control |
| **Docker & Docker Compose** | *(Optional)* v24+ / Compose v2+ | Containerized local or production stack |

---

## 📥 1. Clone the Repository

Open your terminal or PowerShell and clone the repository:

```bash
git clone https://github.com/EhsaasBhalla/HandoffScope.git
cd HandoffScope
```

---

## ⚙️ 2. Environment Configuration

Copy the example environment configuration into `.env` at the project root or in `backend/`:

```bash
# On Linux / macOS:
cp .env.example .env

# On Windows (PowerShell):
copy .env.example .env
```

### Key Environment Variables

| Variable | Default (Local Dev) | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./handoffscope.db` | Database connection string. Use SQLite for instant setup or PostgreSQL (`postgresql+psycopg2://user:pass@localhost:5432/handoffscope`). |
| `SECRET_KEY` | *(Pre-configured dev key)* | Cryptographic key used for JWT authentication and session tokens. |
| `LLM_PROVIDER` | `mock` | `gemini` or `mock`. Defaults to the deterministic offline `MockLLMProvider` for instant zero-API-key execution. |
| `GEMINI_API_KEY` | *(Optional)* | Google Gemini API key if using live cloud models (`gemini-3.5-flash`). |
| `UPLOAD_DIR` | `./storage/uploads` | Path for storing uploaded technical documentation and compliance packages. |
| `VITE_API_URL` | `http://localhost:8000` | Frontend target URL for backend API calls. |

---

## ⚡ Option A: Local Development Setup (Without Docker)

This is the fastest method for local iteration and interactive development.

### Step 1: Start the Backend (FastAPI)

1. Open a terminal and navigate to the backend directory:
   ```bash
   cd backend
   ```

2. Create and activate a Python virtual environment:
   - **Linux / macOS:**
     ```bash
     python3 -m venv venv
     source venv/bin/activate
     ```
   - **Windows (PowerShell):**
     ```powershell
     python -m venv venv
     .\venv\Scripts\Activate.ps1
     ```

3. Install dependencies from `requirements.txt`:
   ```bash
   pip install --upgrade pip
   pip install -r requirements-dev.txt
   ```
   *(Or for production-only dependencies: `pip install -r requirements.txt`)*

4. Seed the demo database:
   The seed script is idempotent and automatically provisions users, workspaces, projects, synthetic source history, transfer packs, and pre-approved version snapshots:
   ```bash
   python -m app.seed.demo_seed
   ```

5. Start the FastAPI development server:
   ```bash
   python -m uvicorn app.main:app --reload --port 8000
   ```

6. Verify the backend is operational:
   - **Health Check:** [http://localhost:8000/health](http://localhost:8000/health)
   - **OpenAPI Interactive Docs (Swagger UI):** [http://localhost:8000/api/v1/docs](http://localhost:8000/api/v1/docs)

---

### Step 2: Start the Frontend (React + Vite)

1. Open a second terminal window and navigate to the frontend directory:
   ```bash
   cd frontend
   ```

2. Install Node dependencies:
   ```bash
   npm install
   ```

3. Start the Vite development server:
   ```bash
   npm run dev
   ```

4. Access the web application:
   - Open your browser to [http://localhost:5173](http://localhost:5173).

---

## 🐳 Option B: Running with Docker & Docker Compose

Docker Compose provisions the PostgreSQL database, the FastAPI backend, and the Vite frontend simultaneously.

### 1. Development Mode (with Volume Mounts & Live Reloading)

```bash
# Run from the repository root:
docker compose up --build
```

- **Frontend:** [http://localhost:5173](http://localhost:5173)
- **Backend API:** [http://localhost:8000](http://localhost:8000)
- **PostgreSQL Database:** `localhost:5432` (`handoffscope` / `handoffscope_dev`)

### 2. Production Stack (Isolated, Optimized Containers)

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

### 3. Stopping the Containers

```bash
docker compose down
```

---

## 🔑 Pre-Seeded Demo Accounts & Credentials

All seeded personas use the shared development password: **`handoffscope-dev-2026`**

| Persona | Email | Primary Role | Key Permissions & Visible Features |
|---|---|---|---|
| **Maya Sharma** | `maya.sharma@example.test` | **Lead / Owner** | Full workspace management, Project creation, Case creation, Ingestion sources, Git History, Audit Log, Settings |
| **Arjun Patel** | `arjun.patel@example.test` | **Departing Dev** | Case #1 participant view, Source history inspection, Question answering |
| **Kabir Singh** | `kabir.singh@example.test` | **Reviewer** | Review Queue, Verification checklist, Snapshot approval (`v1`) |
| **Aisha Khan** | `aisha.khan@example.test` | **Successor** | Successor continuation workspace, Transfer pack acceptance/decline, Clearance redaction notices |
| **Neha Gupta** | `neha.gupta@example.test` | **Contributor** | Observability & Tracing, Document viewing |

---

## 🧪 Interactive Feature Walkthrough Guide

Follow these steps in your browser to test all updated capabilities of HandoffScope:

### 1. Sign In & Session Persistence
1. Navigate to [http://localhost:5173/login](http://localhost:5173/login).
2. Use the quick-fill button or enter `maya.sharma@example.test` with password `handoffscope-dev-2026`.
3. Click **Sign in** to enter the **Overview Dashboard**.
4. Refresh the page: the session persists seamlessly via secure HttpOnly JWT cookies.

---

### 2. Project Git History (GitHub-Style Timeline)
1. Go to **Projects** (`/projects`) and select **Atlas Platform**.
2. Click the **Git History** tab:
   - Notice the chronological, date-grouped list of commit events from connected repositories.
   - Use the search bar to filter by commit message (e.g. `pubsub` or `auth`) or SHA.
   - Click the short SHA button to copy the commit hash to your clipboard.
   - Click **Expand** to view the full commit body.
   - Click the external link icon to open the commit directly on GitHub in a new tab.

---

### 3. Technical Documents & Inline Preview ("Open in New Tab")
1. Open the **Sources** tab under Atlas Platform (or navigate to `/sources`).
2. In the **Uploaded Documents** section, view the parsed runbooks and architecture specifications.
3. Click any document or evidence citation link:
   - The document opens directly in a new browser tab via `/api/v1/documents/{id}/view` (`Content-Disposition: inline`), displaying markdown, PDF, or text natively without forcing a download dialog.
4. Test uploading a new `.md`, `.pdf`, `.docx`, or `.txt` file using the drag-and-drop zone.

---

### 4. Architectural Decision Regeneration
1. Navigate to **Handover Cases** (`/cases`) and open **Case #1 ("Arjun Patel - Atlas Platform Handover")**.
2. In the **Transfer Packs** tab, open **Authentication API & Multi-Tenancy**.
3. Observe the architectural claims (marked with the `DECISION` badge).
4. Click the **Regenerate** button on an individual decision claim, or click **Regenerate Decisions** in the pack/review toolbar:
   - The platform re-scans connected repository commits, PRs, and runbooks.
   - Architectural rationale, groundings, and timestamps are re-synthesized.
   - The freshness state updates to `CURRENT` with an immutable audit entry.

---

### 5. Targeted Questions & Resource Attachments
1. Inside Case #1, navigate to the **Questions** tab.
2. Select any open question (or click **"New Question"** to create one).
3. Click **"Generate Evidence Draft"** to synthesize an AI response grounded with citations.
4. Click **"Answer Question"** (or add a human-confirmed answer):
   - Click **"Attach Document"**: Upload a local specification file to attach it directly to the response.
   - Click **"Attach from Repo"**: Select an existing commit or pull request from the connected GitHub repository.
   - Click **"Submit Human Answer"**.
   - Notice the response displays clean **Attached Resources** pills with direct **Open in New Tab** links.
5. Log in as a Reviewer (**Kabir Singh**) and accept or amend the answer in the **Review Queue** (`/review`).

---

### 6. Review & Immutable Snapshot Approval
1. While logged in as **Kabir Singh**, navigate to the **Review Queue** (`/review`).
2. Inspect claims filtered by state (`PENDING_REVIEW`, `ACCEPTED`, `NEEDS_CLARIFICATION`).
3. Click **"Approve Version Snapshot"**:
   - Creates an immutable JSON version snapshot (`v1`, `v2`, etc.).
   - Sealing the snapshot guarantees that subsequent code changes or documentation updates cannot tamper with historical records.

---

### 7. Successor Continuation & Clearance Redaction
1. Sign in as **Aisha Khan** (`aisha.khan@example.test` - Designated Successor).
2. Open **Successor View** (`/successor`):
   - Notice the **Access Blockers & Redaction Guarantee**: confidential credential documents are withheld with an explicit notice (*"Restricted Evidence Withheld — Evidence source requires elevated clearance"*).
   - Review the 4 operational continuation pillars:
     1. *What am I taking over?* (Transfer packs and claims)
     2. *What are my next actions?* (Operational checklist)
     3. *What is unfinished?* (Knowledge gaps and risks)
     4. *What do I not have access to?* (Blocked credentials and accounts)
3. Formally acknowledge case receipt.
4. **Accept** the *Authentication API* pack and **Decline** the *Payment Integration* pack (providing the mandatory reason).
5. Notice the case lifecycle transitions to **`PARTIALLY_ACKNOWLEDGED`** rather than fabricating a false complete handover.

---

### 8. Enterprise Compliance Package Export
1. Inside the case header, click **"Export Compliance Package"**.
2. Select ZIP or PDF format.
3. The platform generates an offline-verifiable export bundle containing:
   - Full case metadata and participant sign-offs
   - Immutably sealed claim snapshots with citations
   - Cryptographic Ed25519 digital signature and public key for external verification

---

## 🧪 Running Automated Tests

Run the test suite from the `backend/` directory:

```bash
cd backend

# Run all 69 tests:
python -m pytest tests/ -v

# Run the end-to-end pipeline test specifically:
python -m pytest tests/api/test_pipeline_e2e_git_decisions_resources.py -v
```

Expected output:
```text
======================== 69 passed, 1 warning in 30.49s ========================
```

To verify the frontend compilation and bundles:
```bash
cd frontend
npm run build
```

Expected output:
```text
✓ 1706 modules transformed.
dist/index.html ...
✓ built in ~17s
```

---

## 🛠️ Troubleshooting & FAQ

- **Database locking issues on Windows with SQLite?**
  - Ensure other processes (e.g. SQLite browser) have closed `handoffscope.db`. The application uses connection pooling and WAL mode for concurrent access.
- **Port 8000 or 5173 already in use?**
  - Run the backend on an alternate port: `uvicorn app.main:app --port 8001` and update `VITE_API_URL=http://localhost:8001` in `frontend/.env`.
  - Run the frontend on an alternate port: `npm run dev -- --port 5174`.
- **Offline / Mock Mode:**
  - HandoffScope requires no external API keys or cloud connections to run. If `GEMINI_API_KEY` is not present, the system seamlessly falls back to the deterministic `MockLLMProvider`.

---

## 📜 License

MIT License. Built for the Hackathon Engineering Transition Platform Challenge.
