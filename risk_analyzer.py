import os
"""
risk_analyzer.py — Analiză AI cu risc științific
Folosește Claude API pentru analiză structurată pe județe + date Copernicus simulat.
"""

import json
import asyncio
import httpx
from datetime import datetime
from collections import defaultdict
from typing import Optional

# ── CONFIGURARE ────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")  # Setează ca variabilă de mediu
CLAUDE_MODEL      = "claude-sonnet-4-20250514"

# Vectori de risc geografic predeterminate per județ
# Sursa: zone de risc MMAP România, hărți INHGA, Copernicus EMS
ZONE_RISC = {
    # Județe cu risc ridicat inundații (râuri majore + zone depresionare)
    "Galați":     {"inundatie": 8, "poluare_apa": 7, "alunecare": 4},
    "Brăila":     {"inundatie": 8, "poluare_apa": 6, "alunecare": 3},
    "Tulcea":     {"inundatie": 9, "poluare_apa": 7, "alunecare": 2},
    "Ialomița":   {"inundatie": 7, "poluare_apa": 5, "alunecare": 3},
    "Dolj":       {"inundatie": 6, "poluare_apa": 7, "alunecare": 3, "seceta": 6},
    "Gorj":       {"inundatie": 6, "poluare_apa": 8, "alunecare": 7},
    "Vrancea":    {"inundatie": 7, "poluare_apa": 5, "alunecare": 8},
    "Bacău":      {"inundatie": 6, "poluare_apa": 6, "alunecare": 6},
    "Neamț":      {"inundatie": 6, "poluare_apa": 5, "alunecare": 7},
    "Suceava":    {"inundatie": 7, "poluare_apa": 5, "alunecare": 6},
    "Prahova":    {"inundatie": 5, "poluare_apa": 7, "alunecare": 6},
    "Argeș":      {"inundatie": 5, "poluare_apa": 6, "alunecare": 6},
    "Vâlcea":     {"inundatie": 5, "poluare_apa": 5, "alunecare": 7},
    "Mehedinți":  {"inundatie": 6, "poluare_apa": 6, "alunecare": 5},
    "Constanța":  {"inundatie": 4, "poluare_apa": 6, "seceta": 7},
    # Default pentru județe fără date specifice
    "_default":   {"inundatie": 4, "poluare_apa": 4, "alunecare": 4,
                   "poluare_aer": 4, "deseuri": 3, "seceta": 4,
                   "incendiu": 4, "altele": 3},
}

# Keyword-uri relevante per categorie — pentru validare geografică
KEYWORD_RIVERS = {
    "Olt": ["Alba","Vâlcea","Olt","Teleorman","Dolj","Gorj","Sibiu"],
    "Dunăre": ["Mehedinți","Dolj","Olt","Teleorman","Giurgiu","Călărași","Ialomița","Brăila","Galați","Tulcea","Constanța"],
    "Siret": ["Suceava","Bacău","Neamț","Vrancea","Galați"],
    "Prut": ["Botoșani","Iași","Vaslui","Galați"],
    "Mureș": ["Alba","Mureș","Harghita","Hunedoara","Arad"],
    "Someș": ["Cluj","Satu Mare","Bihor","Maramureș","Sălaj"],
    "Jiu":   ["Gorj","Dolj","Mehedinți"],
    "Argeș": ["Argeș","Dâmbovița","Ilfov","Giurgiu"],
    "Prahova":["Prahova","Ilfov"],
    "Cerna": ["Mehedinți","Caraș-Severin"],
}


class RiskAnalyzer:
    """Analizator de risc bazat pe Claude AI + date geografice."""

    def __init__(self):
        self.api_key = ANTHROPIC_API_KEY
        self.copernicus_client = CopernicusClient()

    async def analyze(self, pins: list[dict], report_id: str) -> dict:
        """
        Analiză completă:
        1. Grupare pe județe și categorii
        2. Validare geografică (ex: Oltul în Prahova?)
        3. Date Copernicus/meteo
        4. Scor de risc științific
        5. Analiză AI cu Claude
        6. Generare raport final
        """
        grouped = self._group_pins(pins)
        copernicus_data = await self.copernicus_client.fetch_batch(list(grouped.keys()))

        judete_report = {}

        for judet, judet_pins in grouped.items():
            probleme = []
            by_category = self._group_by_category(judet_pins)

            for category, cat_pins in by_category.items():
                # 1. Validare geografică
                validation = self._validate_geographic(judet, cat_pins)

                # 2. Date meteo/satelit Copernicus
                cop_data = copernicus_data.get(judet, {})

                # 3. Scor de risc
                scor = self._calculate_risk_score(
                    judet=judet,
                    category=category,
                    nr_pinuri=len(cat_pins),
                    validation=validation,
                    copernicus=cop_data,
                )

                # 4. Analiză AI
                ai_eval = await self._ai_evaluate(
                    judet=judet,
                    category=category,
                    pins=cat_pins,
                    validation=validation,
                    copernicus=cop_data,
                    scor=scor,
                )

                probleme.append({
                    "categorie": category,
                    "nr_pinuri": len(cat_pins),
                    "mesaje": [p["text"] for p in cat_pins],
                    "autori": [p["name"] for p in cat_pins],
                    "validare_geografica": validation,
                    "date_copernicus": cop_data,
                    "scor_risc": scor,
                    "nivel_risc": self._risk_level(scor),
                    "evaluare_ai": ai_eval["evaluare"],
                    "recomandari": ai_eval["recomandari"],
                    "factori_stiintifici": ai_eval["factori"],
                })

            # Sortează problemele după scor (descrescător)
            probleme.sort(key=lambda x: x["scor_risc"], reverse=True)
            judete_report[judet] = {
                "nr_total_pinuri": len(judet_pins),
                "scor_maxim": max((p["scor_risc"] for p in probleme), default=0),
                "probleme": probleme,
            }

        return {
            "report_id": report_id,
            "generat_la": datetime.now().isoformat(),
            "pin_count": len(pins),
            "judete": judete_report,
            "sumar_executiv": self._executive_summary(judete_report),
        }

    # ── GRUPARE ─────────────────────────────────────────────────────────────────

    def _group_pins(self, pins: list[dict]) -> dict:
        grouped = defaultdict(list)
        for p in pins:
            grouped[p["judet"]].append(p)
        return dict(grouped)

    def _group_by_category(self, pins: list[dict]) -> dict:
        grouped = defaultdict(list)
        for p in pins:
            grouped[p.get("category", "altele")].append(p)
        return dict(grouped)

    # ── VALIDARE GEOGRAFICĂ ─────────────────────────────────────────────────────

    def _validate_geographic(self, judet: str, pins: list[dict]) -> dict:
        """
        Verifică dacă elementele menționate (râuri etc.) există în județ.
        Returnează: {'valid': bool, 'motivatie': str, 'entitati_detectate': [...]}
        """
        texts = " ".join(p["text"] for p in pins).lower()
        detected = []
        invalid_refs = []

        for river, valid_judete in KEYWORD_RIVERS.items():
            if river.lower() in texts:
                detected.append(river)
                if judet not in valid_judete:
                    invalid_refs.append(
                        f"Râul {river} nu traversează județul {judet}"
                    )

        is_valid = len(invalid_refs) == 0
        return {
            "valid": is_valid,
            "entitati_detectate": detected,
            "referinte_invalide": invalid_refs,
            "motivatie": (
                "Referințele geografice sunt corecte." if is_valid
                else f"Posibil mesaj eronat: {'; '.join(invalid_refs)}"
            ),
        }

    # ── SCOR DE RISC ȘTIINȚIFIC ─────────────────────────────────────────────────

    def _calculate_risk_score(
        self,
        judet: str,
        category: str,
        nr_pinuri: int,
        validation: dict,
        copernicus: dict,
    ) -> float:
        """
        Scor 1-10 bazat pe:
        A) Baza de risc geografic (zona predefinită)          — max 3 pct
        B) Volumul de raportări (nr pin-uri)                  — max 2 pct
        C) Date Copernicus (precipitații, umiditate, NDVI)    — max 3 pct
        D) Penalizare dacă referința geografică e invalidă    — -2 pct
        """
        zone = ZONE_RISC.get(judet, ZONE_RISC["_default"])
        cat_map = {
            "inundatie": "inundatie", "poluare_apa": "poluare_apa",
            "alunecare": "alunecare", "poluare_aer": "poluare_aer",
            "deseuri": "deseuri", "seceta": "seceta",
            "incendiu": "incendiu", "altele": "altele",
        }
        base_risk = zone.get(cat_map.get(category, "altele"), 3)
        A = base_risk * 0.3  # normalizat la max 3

        # B — volum raportări (logaritmic pentru a evita supraponderea)
        import math
        B = min(2.0, math.log1p(nr_pinuri) * 0.8)

        # C — date Copernicus
        C = 0.0
        if copernicus:
            precip  = copernicus.get("precipitatii_mm", 0)
            umiditate = copernicus.get("umiditate_sol_pct", 0)
            ndvi    = copernicus.get("ndvi", 0.5)
            temp    = copernicus.get("temperatura_c", 20)

            if category in ("inundatie", "poluare_apa"):
                C += min(1.5, precip / 30)          # Precipitații > 30mm → risc maxim
                C += min(1.0, umiditate / 80)       # Umiditate sol ridicată
                C += 0.5 if precip > 50 else 0      # Bonus precipitații extreme

            elif category == "alunecare":
                C += min(1.0, precip / 40)
                C += min(1.0, umiditate / 70)
                C += 1.0 if ndvi < 0.2 else 0       # Vegetație redusă → risc mai mare

            elif category == "seceta":
                C += min(1.5, max(0, (temp - 30) / 10))
                C += min(1.5, max(0, (0.5 - ndvi) * 3))

            elif category in ("incendiu",):
                C += min(1.5, max(0, (temp - 28) / 8))
                C += min(1.5, max(0, (0.4 - ndvi) * 4)) if ndvi < 0.4 else 0

            else:
                C = 1.0  # Scor neutru pentru categorii fără date specifice

            C = min(3.0, C)

        # D — penalizare referință geografică invalidă
        D = -2.0 if not validation["valid"] else 0.0

        scor = A + B + C + D
        return round(max(1.0, min(10.0, scor)), 1)

    def _risk_level(self, scor: float) -> str:
        if scor >= 8:   return "CRITIC"
        if scor >= 6:   return "RIDICAT"
        if scor >= 4:   return "MODERAT"
        return "SCĂZUT"

    # ── ANALIZĂ AI (CLAUDE) ─────────────────────────────────────────────────────

    async def _ai_evaluate(
        self, judet: str, category: str, pins: list[dict],
        validation: dict, copernicus: dict, scor: float
    ) -> dict:
        """Trimite datele la Claude pentru evaluare științifică și recomandări."""

        if not self.api_key:
            return self._fallback_evaluation(judet, category, scor, validation)

        mesaje = "\n".join(
            f"- {p['name']}: \"{p['text']}\"" for p in pins
        )

        cop_text = json.dumps(copernicus, ensure_ascii=False) if copernicus else "Date indisponibile"

        prompt = f"""Ești un expert în monitorizarea mediului și managementul riscurilor de mediu în România.

DATE PRIMITE:
- Județ: {judet}
- Categorie problemă: {category}
- Scor risc calculat: {scor}/10 ({self._risk_level(scor)})
- Nr. raportări cetățeni: {len(pins)}
- Validare geografică: {json.dumps(validation, ensure_ascii=False)}
- Date Copernicus/satelit: {cop_text}

MESAJE CETĂȚENI:
{mesaje}

SARCINĂ:
Analizează aceste date din perspectivă STRICT ȘTIINȚIFICĂ și returnează un JSON cu această structură exactă:
{{
  "evaluare": "Paragraf de 2-3 propoziții cu evaluarea situației din perspectivă hidrologică/ecologică/meteorologică. Menționează dacă datele cetățenilor sunt consistente cu datele satelit Copernicus.",
  "factori": ["factor științific 1", "factor 2", "factor 3"],
  "recomandari": [
    "Recomandare concretă 1 (ex: alertă INHGA, inspecție ANPM)",
    "Recomandare concretă 2 (ex: monitorizare calitate apă, prelevare probe)",
    "Recomandare concretă 3 (ex: notificare prefectură, activare plan local)"
  ]
}}

Răspunde DOAR cu JSON-ul, fără text suplimentar.
Factorii trebuie să fie termeni științifici relevanți (ex: 'debit hidrologic crescut', 'saturație sol', 'indice NDVI scăzut').
Recomandările să fie adresate autorităților române competente (INHGA, ANPM, ISU, ANIF, prefectură).
"""

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": CLAUDE_MODEL,
                        "max_tokens": 800,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                resp.raise_for_status()
                content = resp.json()["content"][0]["text"].strip()

                # Curăță eventuale backtick-uri
                content = content.replace("```json", "").replace("```", "").strip()
                return json.loads(content)

        except Exception as e:
            print(f"Eroare Claude API: {e}")
            return self._fallback_evaluation(judet, category, scor, validation)

    def _fallback_evaluation(self, judet, category, scor, validation) -> dict:
        """Evaluare de rezervă dacă API-ul Claude nu e disponibil."""
        geo_note = "" if validation["valid"] else " ATENȚIE: referința geografică poate fi eronată."
        return {
            "evaluare": (
                f"Probleme de tip '{category}' raportate în județul {judet} "
                f"cu scor de risc {scor}/10.{geo_note} "
                f"Evaluarea completă necesită API key Claude configurat."
            ),
            "factori": ["volum raportări cetățeni", "zona de risc predefinită", "date satelit"],
            "recomandari": [
                "Verificare teren de către inspectorat de mediu local",
                "Corelare cu datele INHGA / ANPM pentru zona afectată",
                "Informare prefectură județeană pentru luare de măsuri",
            ],
        }

    # ── SUMAR EXECUTIV ──────────────────────────────────────────────────────────

    def _executive_summary(self, judete_report: dict) -> dict:
        judete_critic  = [j for j, d in judete_report.items() if d["scor_maxim"] >= 8]
        judete_ridicat = [j for j, d in judete_report.items() if 6 <= d["scor_maxim"] < 8]
        judete_moderat = [j for j, d in judete_report.items() if 4 <= d["scor_maxim"] < 6]

        return {
            "total_judete_afectate": len(judete_report),
            "judete_critic":  judete_critic,
            "judete_ridicat": judete_ridicat,
            "judete_moderat": judete_moderat,
            "prioritate_interventie": judete_critic + judete_ridicat,
            "nota": (
                "Județele cu scor CRITIC necesită intervenție imediată. "
                "Raportul este generat automat și necesită validare de un operator uman "
                "înainte de transmiterea la minister."
            ),
        }


# ── CLIENT COPERNICUS (simulat + real) ─────────────────────────────────────────

class CopernicusClient:
    """
    Client pentru date Copernicus Emergency Management Service (EMS) și
    Copernicus Climate Change Service (C3S).

    În prezent returnează date simulate realiste per județ.
    Pentru date reale, conectează-te la:
    - https://cds.climate.copernicus.eu/api/v2
    - https://emergency.copernicus.eu/mapping/ows/wms
    """

    # Date meteo/satelit simulate — bazate pe medii climatice și sezon curent
    # Înlocuiește cu apeluri API reale pentru producție
    SIMULATED_DATA = {
        "Gorj":       {"precipitatii_mm": 45, "umiditate_sol_pct": 78, "ndvi": 0.62, "temperatura_c": 18},
        "Dolj":       {"precipitatii_mm": 38, "umiditate_sol_pct": 65, "ndvi": 0.55, "temperatura_c": 22},
        "Galați":     {"precipitatii_mm": 55, "umiditate_sol_pct": 82, "ndvi": 0.48, "temperatura_c": 16},
        "Brăila":     {"precipitatii_mm": 52, "umiditate_sol_pct": 80, "ndvi": 0.50, "temperatura_c": 17},
        "Tulcea":     {"precipitatii_mm": 60, "umiditate_sol_pct": 85, "ndvi": 0.52, "temperatura_c": 15},
        "Vrancea":    {"precipitatii_mm": 48, "umiditate_sol_pct": 75, "ndvi": 0.65, "temperatura_c": 17},
        "Bacău":      {"precipitatii_mm": 42, "umiditate_sol_pct": 70, "ndvi": 0.60, "temperatura_c": 16},
        "Prahova":    {"precipitatii_mm": 40, "umiditate_sol_pct": 68, "ndvi": 0.58, "temperatura_c": 19},
        "Constanța":  {"precipitatii_mm": 15, "umiditate_sol_pct": 35, "ndvi": 0.30, "temperatura_c": 28},
        "Ialomița":   {"precipitatii_mm": 30, "umiditate_sol_pct": 55, "ndvi": 0.42, "temperatura_c": 24},
        "_default":   {"precipitatii_mm": 25, "umiditate_sol_pct": 55, "ndvi": 0.50, "temperatura_c": 20},
    }

    async def fetch_batch(self, judete: list[str]) -> dict:
        """Returnează date pentru mai multe județe simultan."""
        # TODO: Înlocuiește cu apel real la Copernicus API
        # Exemplu apel real C3S:
        # import cdsapi
        # c = cdsapi.Client()
        # c.retrieve('reanalysis-era5-land', {...}, 'output.nc')
        await asyncio.sleep(0.1)  # Simulăm latența API
        return {
            j: self.SIMULATED_DATA.get(j, self.SIMULATED_DATA["_default"])
            for j in judete
        }


# ── IMPORT LIPSĂ ──────────────────────────────────────────────────────────────
import os
