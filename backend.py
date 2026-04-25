"""
backend.py — API principal FastAPI
Pornire: uvicorn backend:app --reload --port 8000
"""

import uuid
import json
import csv
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from risk_analyzer import RiskAnalyzer

# ── CONFIGURARE ────────────────────────────────────────────────────────────────
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

PINS_FILE    = DATA_DIR / "pins.json"
REPORTS_DIR  = DATA_DIR / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Monitorizare Mediu România", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # În producție, restricționează la domeniul tău
    allow_methods=["*"],
    allow_headers=["*"],
)

analyzer = RiskAnalyzer()

# ── MODELE PYDANTIC ────────────────────────────────────────────────────────────
class Pin(BaseModel):
    id: int
    name: str
    text: str
    category: str
    lat: float
    lng: float
    judet: str
    trimis: bool
    creat_la: str

class PinBatch(BaseModel):
    pins: list[Pin]
    judete: dict   # { "Gorj": [...], "Dolj": [...] }

# ── STOCARE LOCALĂ ─────────────────────────────────────────────────────────────
def load_pins() -> list[dict]:
    if PINS_FILE.exists():
        with open(PINS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []

def save_pins(pins: list[dict]):
    with open(PINS_FILE, "w", encoding="utf-8") as f:
        json.dump(pins, f, ensure_ascii=False, indent=2)

# ── ENDPOINT-URI ───────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "ok", "service": "Monitorizare Mediu România"}


@app.post("/api/pins")
async def receive_pins(batch: PinBatch, background_tasks: BackgroundTasks):
    """Primește pin-urile de pe hartă și declanșează analiza AI în fundal."""
    if not batch.pins:
        raise HTTPException(status_code=400, detail="Niciun pin primit.")

    # Salvează pin-urile
    existing = load_pins()
    existing_ids = {p["id"] for p in existing}
    new_pins = [p.model_dump() for p in batch.pins if p.id not in existing_ids]
    existing.extend(new_pins)
    save_pins(existing)

    report_id = str(uuid.uuid4())[:8]

    # Analiză AI în fundal (nu blochează răspunsul)
    background_tasks.add_task(
        run_analysis_and_save,
        pins=new_pins,
        report_id=report_id
    )

    return {
        "status": "ok",
        "received": len(new_pins),
        "duplicates_skipped": len(batch.pins) - len(new_pins),
        "report_id": report_id,
        "message": f"Analiza AI rulează în fundal. Raport ID: {report_id}"
    }


@app.get("/api/pins")
def get_all_pins():
    """Returnează toate pin-urile stocate, grupate pe județe."""
    pins = load_pins()
    grouped = {}
    for p in pins:
        j = p["judet"]
        grouped.setdefault(j, []).append(p)
    return {
        "total": len(pins),
        "judete": len(grouped),
        "data": grouped
    }


@app.get("/api/reports")
def list_reports():
    """Listează toate rapoartele generate."""
    reports = []
    for f in sorted(REPORTS_DIR.glob("*.json"), reverse=True):
        with open(f, encoding="utf-8") as fp:
            meta = json.load(fp)
            reports.append({
                "report_id": meta.get("report_id"),
                "generat_la": meta.get("generat_la"),
                "total_judete": len(meta.get("judete", {})),
                "pin_count": meta.get("pin_count", 0),
            })
    return {"reports": reports}


@app.get("/api/reports/{report_id}")
def get_report(report_id: str):
    """Returnează un raport specific."""
    path = REPORTS_DIR / f"{report_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Raport negăsit.")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@app.get("/api/reports/{report_id}/csv")
def download_report_csv(report_id: str):
    """Descarcă raportul ca CSV."""
    path = REPORTS_DIR / f"{report_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Raport negăsit.")
    with open(path, encoding="utf-8") as f:
        report = json.load(f)

    csv_path = REPORTS_DIR / f"{report_id}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["Județ", "Categorie problemă", "Nr. pin-uri",
                          "Scor risc (1-10)", "Evaluare AI", "Recomandări"])
        for judet, data in report.get("judete", {}).items():
            for problema in data.get("probleme", []):
                writer.writerow([
                    judet,
                    problema.get("categorie", ""),
                    problema.get("nr_pinuri", 0),
                    problema.get("scor_risc", 0),
                    problema.get("evaluare_ai", ""),
                    " | ".join(problema.get("recomandari", []))
                ])
    return FileResponse(csv_path, filename=f"raport_{report_id}.csv",
                        media_type="text/csv")


@app.delete("/api/pins")
def clear_pins():
    """Șterge toate pin-urile (pentru testare)."""
    save_pins([])
    return {"status": "ok", "message": "Toate pin-urile au fost șterse."}


# ── FUNCȚIE ANALIZĂ FUNDAL ─────────────────────────────────────────────────────
async def run_analysis_and_save(pins: list[dict], report_id: str):
    """Rulează analiza AI și salvează raportul."""
    try:
        print(f"[{report_id}] Pornesc analiza AI pentru {len(pins)} pin-uri...")
        report = await analyzer.analyze(pins, report_id)

        report_path = REPORTS_DIR / f"{report_id}.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        print(f"[{report_id}] Raport salvat: {report_path}")
    except Exception as e:
        print(f"[{report_id}] Eroare analiză: {e}")
        # Salvează raport de eroare
        error_report = {
            "report_id": report_id,
            "generat_la": datetime.now().isoformat(),
            "eroare": str(e),
            "pin_count": len(pins)
        }
        with open(REPORTS_DIR / f"{report_id}.json", "w", encoding="utf-8") as f:
            json.dump(error_report, f, ensure_ascii=False, indent=2)


# ── PORNIRE DIRECTĂ ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend:app", host="0.0.0.0", port=8000, reload=True)
