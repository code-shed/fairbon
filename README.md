<div align="center">

# 🛒 FairBon

**Open-Source Haushaltsbuch & Preisvergleich für deutsche Supermärkte**  
*Datenschutz-first · Lokal · Community-getrieben*

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](LICENSE)
[![Project Board](https://img.shields.io/badge/Project%20Board-GitHub%20Projects-6f42c1)](https://github.com/users/code-shed/projects/1)
[![Status: Early Alpha](https://img.shields.io/badge/Status-Early%20Alpha-orange)]()

</div>

---

## 🎯 Was ist FairBon?

FairBon hilft dir, **Einkäufe zu tracken, Preise zu vergleichen und Geld zu sparen** – **ohne dass deine Daten je deinen Rechner verlassen**.

| Feature | Status | Beschreibung |
|---------|--------|--------------|
| 🧾 **Kassenbon-Import** (OCR / manuell) | 🚧 *In Planung* | Foto → strukturierte Positionen (Artikel, Menge, Preis, Angebot/Regalpreis) |
| 📊 **Preisverlauf & History** | 🚧 *In Planung* | Wie hat sich der Preis von „Hafermilch 1L“ über 6 Monate entwickelt? |
| 🏷 **Angebote vs. Standardpreise** | 💡 *Konzept* | Erkennen: „Ist das gerade ein echtes Angebot oder der normale Preis?“ |
| 🛍 **Smart Basket** | 💡 *Konzept* | „Ich brauche Milch, Haferflocken, Äpfel – wo ist der Korb *heute* am günstigsten?“ |
| 🔒 **100 % lokal / offline-first** | ✅ *Design-Prinzip* | Keine Cloud, kein Tracking, keine Accounts – deine Daten, deine Regeln |
| 🇩🇪 **Fokus: DE-Supermärkte** | ✅ *Scope* | REWE, EDEKA, Aldi, Lidl, Netto, Penny, Kaufland, dm, Rossmann, … |

> **Warum AGPL-3.0?**  
> Wenn jemand FairBon als Web-Service betreibt und den Code anpasst, *muss* er die Änderungen veröffentlichen. Das garantiert langfristig: **Deine Daten bleiben deine.**

---

## 🚀 Quickstart (Entwicklung)

> ⚠️ **Early Alpha** – Noch kein lauffähiger Code. Die Struktur wird gerade aufgebaut.

```bash
# 1. Repository klonen
git clone https://github.com/code-shed/fairbon.git
cd fairbon

# 2. Python-Umgebung (empfohlen: uv oder venv)
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"   # sobald pyproject.toml existiert

# 3. Pre-Commit Hooks (später)
pre-commit install

# 4. Tests laufen lassen
pytest -q
```

**Geplanter Tech-Stack** (Diskussion offen – siehe [Issues](https://github.com/code-shed/fairbon/issues)):
- **Backend:** Python (FastAPI / SQLAlchemy / Pydantic) – lokal als Single-Binary oder Docker
- **Frontend:** Web-UI (HTMX + Tailwind oder React) + optional Native Desktop (Tauri/Electron)
- **OCR:** Tesseract / PaddleOCR / Apple Vision / Google ML Kit (lokal)
- **Datenhaltung:** SQLite (lokal), später evtl. DuckDB für Analysen

---

## 🤝 Mitmachen – Contributing Guide

Wir freuen uns über **jede Art von Beitrag**: Code, Docs, Issues, Ideen, Tests, Übersetzungen, Design.

### 1. Projektboard & Arbeitspakete
👉 **zentrale Übersicht:** [GitHub Project Board „@fairbon“](https://github.com/users/code-shed/projects/1)  
Dort siehst du: Backlog → Ready → In Progress → Review → Done

### 2. Guter erster Schritt
- Schau in die **Issues** (Label `good first issue`, `help wanted`)
- Oder eröffne ein **neues Issue** für Bug, Feature, Frage
- Kommentiere: „Ich schau mir das an“ – dann assignen wir es dir

### 3. Workflow
```text
main (geschützt)
  ↑ PR (Review + CI green)
feature/kurz-beschreibung   (dein Branch)
  ↑ commits (conventional: feat:, fix:, docs:, refactor:, test:, chore:)
```

- **Commits:** Konventionelle Commits (`feat: add receipt parser`)
- **PR-Template** wird folgen – bis dahin: kurz beschreiben *Was & Warum*
- **Tests & Lint** müssen grün sein (CI kommt mit erstem Code)

### 4. Verhaltenskodex
Freundlich, konstruktiv, respektvoll – [Contributor Covenant](https://www.contributor-covenant.org/) (wird verlinkt, sobald `CODE_OF_CONDUCT.md` liegt).

---

## 🗺 Roadmap (High-Level)

| Phase | Ziel | Meilenstein |
|-------|------|-------------|
| **0** | Repo-Struktur, CI, Dev-Setup, Lizenz | ✅ *läuft gerade* |
| **1** | Datenmodell (Artikel, Märkte, Preise, Bons), SQLite-Schema, Basis-CRUD | 🎯 *nächstes* |
| **2** | Kassenbon-Import (manuell + OCR-Prototyp) | |
| **3** | Preisverlauf, Charts, Export (CSV/JSON) | |
| **4** | Smart Basket & Preisvergleich über Märkte | |
| **5** | Desktop-App (Tauri), Installer, Auto-Update | |
| **6** | Community-Features: Preis-Meldungen, Crowd-Sourcing (opt-in, anonym) | |

---

## 📂 Projektstruktur (geplant)

```text
fairbon/
├── .github/                 # Workflows, Issue/PR-Templates
├── docs/                    # Architektur, ADRs, API-Docs
├── fairbon/                 # Python-Package (Backend)
│   ├── api/                 # FastAPI-Router
│   ├── core/                # Config, Security, DB
│   ├── models/              # SQLAlchemy/Pydantic
│   ├── services/            # Business-Logik (OCR, Matching, Analytics)
│   └── cli.py               # Typer/Click CLI
├── frontend/                # Web-UI (später)
├── tests/                   # pytest (unit + integration)
├── scripts/                 # Dev-Helpers (db-migrate, seed, etc.)
├── pyproject.toml           # Build, deps, tool-config (ruff, mypy, pytest)
├── .gitignore
├── LICENSE                  # AGPL-3.0
└── README.md                # diese Datei
```

---

## 📜 Lizenz & Copyright

**AGPL-3.0-or-later** – siehe [`LICENSE`](LICENSE)  
Copyright © 2024 **code-shed** & Contributors

> Kurz: **Nutzen, ändern, teilen erlaubt – aber gehostete Änderungen müssen offen gelegt werden.**

---

## 💬 Kontakt & Community

- **Issues & Diskussionen:** [GitHub Issues](https://github.com/code-shed/fairbon/issues)
- **Projektboard:** [https://github.com/users/code-shed/projects/1](https://github.com/users/code-shed/projects/1)
- **Später:** Discord / Matrix / Forum (wenn Bedarf da ist)

---

<div align="center">

**FairBon wird von der Community für die Community gebaut.**  
⭐ Stern das Repo, wenn du die Idee magst – das hilft bei Sichtbarkeit!

</div>