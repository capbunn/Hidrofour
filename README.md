# Monitorizare Mediu România — Sistem Crowdsourcing

## Structura proiectului

```
├── index.html          ← Frontend: hartă + formulare pin-uri
├── backend.py          ← API FastAPI: primește pin-uri, generează rapoarte
├── risk_analyzer.py    ← Analiză AI: scor risc + evaluare Claude
├── requirements.txt    ← Dependențe Python
└── data/               ← Date stocate local (creat automat)
    ├── pins.json
    └── reports/
```

---

## 1. Instalare Python backend

```bash
# Creează mediu virtual
python -m venv venv
source venv/bin/activate        # Linux/Mac
venv\Scripts\activate           # Windows

# Instalează dependențele
pip install -r requirements.txt
```

---

## 2. Configurare API key Claude

```bash
# Linux / Mac
export ANTHROPIC_API_KEY="sk-ant-..."

# Windows PowerShell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
```

Obții key-ul de la: https://console.anthropic.com

---

## 3. Pornire server backend

```bash
python backend.py
# sau
uvicorn backend:app --reload --port 8000
```

Serverul pornește la: http://localhost:8000
Documentație API automată: http://localhost:8000/docs

---

## 4. Deschide frontend

Deschide `index.html` în browser (dublu click sau drag în browser).

Sau cu un server simplu:
```bash
python -m http.server 3000
# apoi deschide http://localhost:3000
```

---

## 5. Flux de utilizare

1. **Cetățeni** → dau click pe hartă → completează numele + mesaj + categorie → Salvează pin
2. **Export** → buton "Export JSON" sau "Export CSV" pentru backup local
3. **Trimite la server** → butonul "Trimite la server" → pin-urile merg la backend
4. **Analiză automată** → backend rulează `risk_analyzer.py` în fundal
5. **Rapoarte** → `GET /api/reports` → lista rapoartelor generate
6. **Operator** → accesează `GET /api/reports/{id}` → validează și trimite la minister

---

## 6. Endpoint-uri API

| Metodă | URL | Descriere |
|--------|-----|-----------|
| POST | `/api/pins` | Primește pin-uri de pe hartă |
| GET | `/api/pins` | Toate pin-urile, grupate pe județe |
| GET | `/api/reports` | Lista rapoartelor generate |
| GET | `/api/reports/{id}` | Raport complet cu scor risc + AI |
| GET | `/api/reports/{id}/csv` | Descarcă raport ca CSV |
| DELETE | `/api/pins` | Șterge toate pin-urile (testare) |

---

## 7. Formula scor de risc (1-10)

```
Scor = A (risc geografic) + B (volum raportări) + C (date Copernicus) + D (penalizare)

A = baza de risc predefinită per județ și categorie     [0–3 pct]
B = log(nr_pinuri) × 0.8                               [0–2 pct]
C = precipitații + umiditate sol + NDVI + temperatură  [0–3 pct]
D = -2 dacă referința geografică e invalidă            [0 sau -2]

Nivel risc:
  1–3   → SCĂZUT
  4–5   → MODERAT
  6–7   → RIDICAT
  8–10  → CRITIC
```

---

## 8. Integrare Copernicus (date reale)

Modifică `CopernicusClient.fetch_batch()` în `risk_analyzer.py`:

```python
import cdsapi

async def fetch_batch(self, judete):
    c = cdsapi.Client()
    c.retrieve(
        'reanalysis-era5-land',
        {
            'variable': ['total_precipitation', 'volumetric_soil_water_layer_1'],
            'year': '2025',
            'month': '04',
            'day': ['01', '02', ...],
            'time': '00:00',
            'format': 'netcdf',
        },
        'copernicus_data.nc'
    )
    # Parsează NetCDF și returnează date per județ
```

Înregistrare gratuită Copernicus: https://cds.climate.copernicus.eu

---

## 9. Deploy producție (opțional)

**Backend pe Railway/Render:**
```bash
# railway.toml
[build]
  command = "pip install -r requirements.txt"

[deploy]
  startCommand = "uvicorn backend:app --host 0.0.0.0 --port $PORT"
```

**Frontend pe GitHub Pages** — încarcă `index.html` și schimbă `BACKEND_URL`.

---

## 10. Exemplu raport generat

```json
{
  "report_id": "a3f7b2c1",
  "generat_la": "2025-04-25T10:30:00",
  "pin_count": 12,
  "sumar_executiv": {
    "judete_critic": ["Galați"],
    "judete_ridicat": ["Gorj", "Dolj"],
    "prioritate_interventie": ["Galați", "Gorj", "Dolj"]
  },
  "judete": {
    "Gorj": {
      "scor_maxim": 7.2,
      "probleme": [{
        "categorie": "poluare_apa",
        "nr_pinuri": 3,
        "scor_risc": 7.2,
        "nivel_risc": "RIDICAT",
        "evaluare_ai": "Raportările cetățenilor indică poluare pe râul Jiu, consistentă cu umiditatea ridicată a solului (78%) și precipitațiile recente de 45mm înregistrate de Copernicus.",
        "recomandari": [
          "Alertă imediată ANPM pentru prelevare probe apă Jiu",
          "Notificare Garda de Mediu Gorj pentru inspecție teren",
          "Corelare cu date INHGA privind debitul Jiu"
        ]
      }]
    }
  }
}
```
