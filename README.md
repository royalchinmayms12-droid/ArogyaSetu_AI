# ArogyaSetu AI — Corrected Prototype

A React + Python healthcare-access prototype with a more reliable health-information assistant, phone-number/password accounts, patient health notes, patient-controlled record sharing, a hospital dashboard, and OpenStreetMap facility search.

## Features
- React + Vite responsive interface (English, Kannada, Hindi)
- Python FastAPI backend
- AI assistant works without an API key using topic-based general-health answers; configure an OpenAI-compatible API for richer responses
- Emergency-symptom messages direct users to urgent help (112 in India)
- Browser speech input/output where supported
- OpenStreetMap/Nominatim/Overpass facility search (internet required)
- Phone-number + password registration and login
- Patient can save health concerns, symptoms, severity, notes, and review their own entries
- Patients choose whether to share saved concerns with hospital accounts
- Hospital dashboard only lists health concerns for patients who opted in to sharing
- SQLite database is created automatically in `backend/arogyasetu.db`
- Basic PWA shell and offline health guide

## Run on Windows (PowerShell / VS Code)

**Prerequisites:** Python 3.10+ and Node.js 18+ (Node 20 LTS recommended). Extract the ZIP first.

### 1. Start the Python backend
Open Terminal 1:

```powershell
cd ArogyaSetu_AI_Corrected\backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

If PowerShell blocks environment activation, run this in that terminal and retry activation:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Confirm the backend is running by opening `http://127.0.0.1:8000/` or `http://127.0.0.1:8000/docs`.

### 2. Start the React frontend
Open Terminal 2 in VS Code:

```powershell
cd ArogyaSetu_AI_Corrected\frontend
npm install
npm run dev
```

Open the Vite URL shown in the terminal, normally `http://localhost:5173`.

### 3. Try the phone login and hospital dashboard
1. Open **Login / Register** in the app.
2. Register a patient using a phone number and a password of at least 8 characters.
3. Open the Portal and save a sample health concern.
4. Enable **Share records with hospital accounts** only if you want to share those saved entries.
5. Sign out, register a separate **Hospital / Clinic staff** prototype account, and open its portal to view consenting patients' shared entries.
6. Use a different browser/private window to test two accounts simultaneously.

The database file is created automatically at `backend/arogyasetu.db`. Keep this file private; it contains account and health-note data. To reset demo data, stop the backend and delete this file.

### 4. Optional AI configuration
**Security:** If you have pasted an API key into a chat, screenshot, email, or public repository, revoke it immediately in your provider dashboard and create a new key. Do not send the new key to anyone or put it in this ZIP. Edit `backend/.env` locally and add your newly created key:

```env
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-4o-mini
OPENAI_BASE_URL=https://api.openai.com/v1
```

Restart the backend after changing `.env`. Never put provider keys in frontend code or commit them to GitHub. Without a key, the assistant still returns basic topic-based general-health guidance and marks those responses as demo/basic guidance.

## Important limitations before real-world use
- This is an educational prototype, **not** a clinically validated medical system.
- Phone number is used as an account identifier, but **SMS OTP/phone ownership verification is not implemented**. Login uses a password. Add a trusted SMS provider and verification workflow before deployment.
- Hospital registration is open in this demo and hospital identities are **not verified**. Do not use real patient data or deploy publicly until hospital onboarding, staff verification, access controls, HTTPS, rate limiting, audit logging, backups, consent withdrawal workflows, data retention/deletion, and a security/privacy review are implemented.
- Patient sharing is opt-in in the prototype. Hospital dashboard only returns records for patients who enabled sharing.
- The database is SQLite for local testing, not a production multi-hospital database.
- The assistant gives general education, not diagnosis, prescriptions, or individualized treatment. Seek qualified medical care for medical concerns; for emergencies in India call 112.
- Map results are community-maintained and may be incomplete or outdated. Confirm services before travelling.
- Do not enter unnecessary identifying or highly sensitive details in demo records.

\n## Troubleshooting AI responses\n
- Open `http://127.0.0.1:8000/api/ai-status`. It should show `configured: true` when `backend/.env` contains a non-empty key. It never returns the key.\n
- If the assistant still says it is using basic/demo guidance, check the **backend terminal** for `AI provider error`. Common causes include an invalid/revoked key (401), model access issue (404), exhausted billing/quota (429), or a network timeout.\n
- Ensure `backend/.env` contains these lines, with your fresh key only on your own computer:\n
  ```env\n  OPENAI_API_KEY=your_new_key_here\n  OPENAI_MODEL=gpt-4o-mini\n  OPENAI_BASE_URL=https://api.openai.com/v1\n  ```\n
- Restart the backend after changing `.env` (Ctrl+C, then `python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000`). Test `/api/health` and `/api/ai-status`.\n
- The hospital map uses public OpenStreetMap community services. Map tiles can load even when the separate facility-search service is unavailable. The app now retries multiple Overpass servers; if all are busy, wait a minute and try again.\n
