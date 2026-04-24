# Experience App — Frontend

Vanilla JS + HTML + CSS MVP. Bez build toolchainu (žádný npm, webpack). Slouží jako tenký klient nad FastAPI backendem.

## Struktura

```
frontend/
├── index.html          # Generátor + historie
├── experience.html     # Detail experience (mapa + zastávky)
├── css/main.css        # Dark theme styly
├── js/
│   ├── api.js          # Fetch vrstva nad backendem
│   ├── map.js          # Leaflet mapa (CDN)
│   ├── generator.js    # Create + polling flow
│   ├── experience.js   # Detail stránka
│   └── history.js      # Seznam experiences
└── assets/icons/       # Volitelné SVG ikony
```

## Jak spustit

1. **Spusť backend** v samostatném terminálu (výchozí: `http://localhost:8000`):

   ```bash
   cd backend
   uvicorn app.main:app --reload
   # nebo mock mode bez API klíčů:
   MOCK_MODE=true uvicorn app.main:app --reload
   ```

2. **Spusť statický server** v `frontend/` složce:

   ```bash
   cd frontend
   python -m http.server 3000
   ```

3. Otevři [http://localhost:3000](http://localhost:3000) v prohlížeči.

## Požadavky

- Backend musí běžet na `http://localhost:8000`.
- CORS musí mít povolené origins `http://localhost:3000` a `http://127.0.0.1:3000`
  (již nakonfigurováno v `backend/app/main.py`).
- Frontend používá CDN pro **Leaflet 1.9.4** — potřebuje internet při prvním
  načtení mapy. Pokud pracuješ offline, stáhni si lokální kopii Leafletu.

## Konfigurace `BASE_URL`

Pokud backend běží jinde než na `localhost:8000`, uprav konstantu v `js/api.js`:

```javascript
const BASE_URL = 'http://localhost:8000';  // nebo např. 'https://api.example.com'
```

## Stránky

- `index.html` — levý panel = generátor s textareou a tlačítkem, pravý panel =
  karty posledních 10 experiences. Polling stavu každé 2 s, timeout 5 min.
- `experience.html?id=<job_id>` — detail: metriky kvality, seznam zastávek s
  médii a Leaflet mapa s markery obarvenými podle `fallback_level`.

## Klávesy

- `Ctrl` / `Cmd` + `Enter` v textarea = spustí generování
- `Enter` / `Space` na historické kartě = navigace na detail

## Poznámky

- Wikimedia obrázky se načítají přes `Special:FilePath` endpoint s `width=400`.
- Pokud stop má `fallback_level === "NO_MEDIA"`, místo obrázku se zobrazí
  placeholder.
- Pokud běží Ollama (`/health` vrací `providers.ollama === "ok"`), zobrazí se
  v patičce model např. `🤖 Ollama: phi3.5`.
