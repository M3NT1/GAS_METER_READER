# Számlálóolvasó modell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Külön keret- és számjegymodell, látható felismerési állapotokkal és indítható tanításokkal.

**Architecture:** A Pipeline a keretdetektort használja kivágási javaslatként, majd a helyi számjegyosztályozót futtatja a nyolc görgőképen. A webalkalmazás külön háttérfolyamatban indítja a két tanítást, és a Store a felismerési állapotot tartja meg.

**Tech Stack:** FastAPI, SQLite, Pillow, Ultralytics YOLO, ONNX Runtime, JavaScript.

**Spec:** `docs/superpowers/specs/2026-09-08-register-reader-design.md`

## Global Constraints

- Csak helyi modell és helyi képkezelés.
- Minden gépi érték emberi ellenőrzésre vár.
- A digitális értékhez mind a nyolc számjegynek el kell érnie a 0,75 biztonságot.

---

### Task 1: Felismerési állapotok

**Files:** `gasphoto/store.py`, `gasphoto/pipeline.py`, `tests/test_store.py`, `tests/test_pipeline.py`

- [ ] Írj bukó tesztet arra, hogy keret esetén `position_identified`, érték esetén `counter_recognized` állapot mentődik.
- [ ] Egészítsd ki a Store és Pipeline mentését.
- [ ] Futtasd a célzott teszteket.

### Task 2: Számjegytanító halmaz és modell

**Files:** `scripts/export_digit_dataset.py`, `scripts/train_digit_classifier.py`, `gasphoto/digits.py`, `tests/test_digits.py`

- [ ] Írj bukó tesztet a nyolc görgőkivágás és a formázott érték előállítására.
- [ ] Exportáld fotószinten szétválasztott 0–9 osztályozóhalmazba a jóváhagyott példákat.
- [ ] Taníts és ONNX-be exportálj helyi osztályozót; futáskor csak teljesen biztos nyolcjegyű eredményt adj vissza.
- [ ] Futtasd a célzott teszteket.

### Task 3: Két tanítási folyamat és felület

**Files:** `gasphoto/web.py`, `gasphoto/static/index.html`, `gasphoto/static/app.js`, `gasphoto/static/style.css`, `tests/test_web.py`

- [ ] Írj bukó API-teszteket mindkét indítási végpontra.
- [ ] Válaszd szét a keret- és számjegytanítás állapotát, naplóját és indítását.
- [ ] A felületen mutasd a két kártyát, a státuszcímkéket és az automatikus értékbeírást.
- [ ] Futtasd a teljes tesztcsomagot.
