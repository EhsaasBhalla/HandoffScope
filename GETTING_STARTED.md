# Getting Started with HandoffScope

This guide explains step-by-step how to launch, explore, and test the **HandoffScope** platform.

---

## 📋 Prerequisites

- **Python 3.12+**
- **Node.js 18+** & **npm 9+**
- *(Optional)* Docker & Docker Compose

---

## ⚡ Quick Launch (Local Development)

### 1. Start the Backend
The backend runs FastAPI with SQLite (`handoffscope.db`) for immediate local execution. On initial startup, it automatically creates the database schema and seeds the demo personas and synthetic history.

```powershell
cd E:\CodeNexus\HandoffScope\backend
python -m uvicorn app.main:app --reload --port 8000
```

- **Health check:** [http://localhost:8000/health](http://localhost:8000/health)
- **Interactive OpenAPI Docs:** [http://localhost:8000/api/v1/docs](http://localhost:8000/api/v1/docs)

---

### 2. Start the Frontend
The frontend is a React 18 single-page application built with Vite 6.

```powershell
cd E:\CodeNexus\HandoffScope\frontend
npm install    # (if not already run)
npm run dev
```

- **Web Application:** [http://localhost:5173](http://localhost:5173)

---

## 🔑 Demo Personas & Credentials

All seeded accounts use the password: **`handoffscope-dev-2026`**

| Persona | Email | Primary Role | Visible Features & Permissions |
|---|---|---|---|
| **Maya Sharma** | `maya.sharma@example.test` | **Lead / Owner** | Full management, Create Project, Create Case, Sources, Audit Log, Settings |
| **Arjun Patel** | `arjun.patel@example.test` | **Departing Dev** | Case #1 participant view, Source history inspection |
| **Neha Gupta** | `neha.gupta@example.test` | **Successor** | Successor view, Recipient-scoped navigation |
| **Aisha Khan** | `aisha.khan@example.test` | **Reviewer** | Review Queue, Verification checklist |

---

## 🧪 Testing the Functionality (Step-by-Step Walkthrough)

### 1. Test Authentication & Session
1. Open [http://localhost:5173/login](http://localhost:5173/login).
2. Click the quick-fill credentials or enter `maya.sharma@example.test` with password `handoffscope-dev-2026`.
3. Click **Sign in**. You are redirected to the **Overview Dashboard**.
4. Refresh the page: notice your session persists automatically via HttpOnly JWT cookies.
5. In the top right, click Maya's avatar menu and test **Sign out**, then log back in.

---

### 2. Test Role-Aware Navigation
1. Log in as **Maya Sharma** (`maya.sharma@example.test`):
   - Notice the sidebar shows the complete navigation suite, including **People & Access**, **Audit Log**, and **Settings**.
2. Log out and log in as **Neha Gupta** (`neha.gupta@example.test` - Successor):
   - Notice the sidebar updates dynamically: administrative tabs are hidden and **Successor View** is visible.

---

### 3. Test Theme Toggle (View Transition API)
1. Click the **Sun / Moon** icon in the topbar.
2. Notice the circular reveal animation transitioning smoothly between **Warm Charcoal** dark mode and **Warm Paper** light mode.
3. Refresh the page: your theme preference is remembered in `localStorage`.

---

### 4. Test Projects & Project Detail
1. Navigate to **Projects** (`/projects`) in the sidebar.
2. Click on the **Atlas Platform** project card.
3. Explore the 4 tabs:
   - **Overview:** Project metrics (Cases, Sources, Team Members).
   - **Handover Cases:** Displays active cases for this project.
   - **Sources:** Lists the pre-connected **Atlas Platform Synthetic History**.
   - **People:** Lists the project members (Maya, Arjun, Neha, Aisha, Kabir, Dev, Priya) with their role badges.
4. Go back to `/projects` and click **"New Project"** to test the project creation modal.

---

### 5. Test Handover Cases & State Machine
1. In the sidebar, click **Handover Cases** (`/cases`).
2. Use the status filter chips (`ALL`, `DRAFT`, `RECONSTRUCTING`, `BLOCKED`, etc.) to filter cases.
3. Click on **Case #1 ("Arjun Patel - Atlas Platform Handover")**:
   - Inspect the **5-stage lifecycle progress indicator** (`Connect` → `Reconstruct` → `Verify` → `Review` → `Handover`).
   - Check the **Case Metadata** and **Participants Roster** (Initiator: Maya, Departing: Arjun, Reviewer: Aisha, Recipient: Neha).
   - Click **"Flag as Blocked"**, enter a reason, and submit: notice the case enters a blocked state with a warning banner.
   - Click **"Clear Block"** to return the case to normal.

---

### 6. Test Creating a Handover Case
1. Navigate to `/projects` → **Atlas Platform** → click **"Create Handover Case"** (or go to `/projects/<id>/cases/new`).
2. Fill out the form:
   - **Title:** e.g. `Payment Gateway Knowledge Transfer`
   - **Transition Type:** Planned Departure
   - **Departing Contributor:** Select `Arjun Patel`
   - **Designated Successor:** Select `Neha Gupta`
   - **Reviewer:** Select `Aisha Khan`
   - **Scope Window:** Choose start and end dates
   - **Scope Context:** Enter notes on payment integration
3. Submit the form: you are automatically redirected to your newly created case.

---

### 7. Test Sources & Document Upload
1. In the sidebar, click **Sources** (`/sources`).
2. Inspect the **GitHub Integration Card** (configured with the Atlas Platform repo).
3. Inspect the **Source Inventory Table** showing the synthetic history with 63 ingested items (18 issues, 10 PRs, 35 commits).
4. Click **"Trigger Sync"** on the source: a notification banner appears with the background Job ID.
5. In the **Document Upload** section, drag-and-drop or select any file (`.pdf`, `.docx`, `.md`, or `.txt`):
   - The file uploads and is parsed automatically.
   - It appears in the **Uploaded Documents** table with file size, format, page/section count, and `COMPLETED` status.

---

### 8. Run Automated Test Suites
Run the automated test suite in the backend terminal:

```powershell
cd E:\CodeNexus\HandoffScope\backend
python -m pytest tests/
```

Expected output:
```text
tests\api\test_health_api.py .
tests\unit\test_parsers.py ..
tests\unit\test_security.py .....
tests\unit\test_state_machine.py ...

11 passed in 3.55s
```

Verify frontend build:
```powershell
cd E:\CodeNexus\HandoffScope\frontend
npm run build
```
Expected output:
```text
✓ built in ~3s with zero errors
```

---

## 🛠️ Troubleshooting

- **CORS or Network Error:** Ensure the backend is running at `http://localhost:8000` and the frontend at `http://localhost:5173`.
- **Database Reset:** To start completely fresh, simply delete `backend/handoffscope.db` and restart uvicorn. The schema and demo accounts will re-seed automatically.
