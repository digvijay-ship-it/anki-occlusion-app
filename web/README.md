# Anki Occlusion Web

First web-port slice:

- `backend/` exposes a FastAPI API over the existing JSON data file.
- `frontend/` contains a Vite React dashboard based on `C:\Users\Digvijay\Desktop\Temp anki\Home.html`.

Run backend:

```powershell
cd web\backend
uvicorn run:app --reload --port 8000
```

Run frontend:

```powershell
cd web\frontend
npm install
npm run dev
```

The frontend reads `VITE_API_BASE`, defaulting to `http://127.0.0.1:8000`.

