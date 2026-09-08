# Telefonfotós, tanuló gázóra-felismerés Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A felhasználó által ellenőrzött telefonfotókból tanuló számlálóablak- és számjegyfelismerő építése a meglévő gázóra-fotónaplóba.

**Architecture:** A meglévő SQLite-napló külön, revízióhoz kötött tanítópéldákat és modellverziókat tárol. A böngészős felület rögzíti a kijelző négyszögét és a jóváhagyott értéket. Az exportált, elkülönített tanítóhalmazból offline YOLO ablakdetektor és pozícióalapú számjegyosztályozó készül; futáskor csak jóváhagyott modell adhat javaslatot.

**Tech Stack:** Python 3.12, FastAPI, SQLite, Pillow, OpenCV, Ultralytics YOLOv8, ONNX Runtime, vanilla JavaScript.

**Spec:** `docs/superpowers/specs/2026-09-07-phone-meter-learning-design.md`

## Global Constraints

- Támogatott forrás: Xiaomi 15T Pro és iPhone 14 Pro Max eredeti JPEG/HEIC.
- EXIF-készítési idő, eredeti archívum és HA-küldési feltételek változatlanok.
- Nincs automatikus jóváhagyás vagy közvetlen HA-írás modellből.
- Csak öt egész és három tizedes számjegy alkot érvényes javaslatot.
- A tanító- és modellfájlok `data/` alatt maradnak és nem kerülnek verziókezelésbe.
- A könyvtár jelenleg nem Git repository; commit-lépés nem hajtható végre.

---

### Task 1: Tanítópéldák és modellverziók tartós tárolása

**Files:**
- Modify: `gasphoto/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Produces: `Store.record_training_example(photo_id, window_quad, value, decision, model_version=None) -> dict`
- Produces: `Store.training_examples() -> list[dict]`, `Store.create_model_version(...) -> dict`

- [ ] **Step 1: Írj hibázó teszteket**

```python
example = store.record_training_example(photo_id, [[.2,.4],[.8,.4],[.8,.5],[.2,.5]], '01817.759', 'corrected')
assert example['value_digits'] == '01817759'
assert store.training_examples()[0]['photo_id'] == photo_id
```

- [ ] **Step 2: Futtasd a céltesztet**

Run: `.venv/bin/python -m pytest tests/test_store.py -q`
Expected: FAIL, mert az új Store-metódusok hiányoznak.

- [ ] **Step 3: Implementáld a sémát és a validációt**

```python
CREATE TABLE training_examples (
 photo_id TEXT NOT NULL, revision INTEGER NOT NULL, window_quad_json TEXT NOT NULL,
 value_digits TEXT NOT NULL, decision TEXT NOT NULL, created_at TEXT NOT NULL,
 model_version TEXT, PRIMARY KEY(photo_id, revision)
)
```

Fogadj csak négy, `[0,1]` tartományú pontot, nem önmetsző négyszöget, jóváhagyott fotórevíziót és nyolc numerikus számjegyet. Mentsd az auditban is a tanítópélda-azonosítót.

- [ ] **Step 4: Futtasd a Store-teszteket**

Run: `.venv/bin/python -m pytest tests/test_store.py -q`
Expected: PASS.

### Task 2: Tanító címke rögzítése és lekérdezése a helyi API-n

**Files:**
- Modify: `gasphoto/web.py`, `gasphoto/pipeline.py`
- Test: `tests/test_web.py`, `tests/test_pipeline.py`

**Interfaces:**
- Produces: `POST /api/photos/{photo_id}/training-example` with `{window_quad, value, decision}`
- Produces: `GET /api/photos/{photo_id}/training-example`

- [ ] **Step 1: Írj hibázó API-tesztet**

```python
r = client.post(url, headers=headers, json={"window_quad": quad, "value":"01817.759", "decision":"corrected"})
assert r.status_code == 200
assert client.get(url).json()['value_digits'] == '01817759'
```

- [ ] **Step 2: Ellenőrizd a hibát**

Run: `.venv/bin/python -m pytest tests/test_web.py -q`
Expected: FAIL 404.

- [ ] **Step 3: Implementáld a Pydantic-kérelmet és a végpontokat**

A kérelem tiltson minden ismeretlen mezőt. A négyszög koordinátáit kizárólag az API validálja, majd a Store tárolja. Az `approve` végpont csak sikeres jóváhagyás után hívhatja a tanítópélda-rögzítést; elutasított, olvashatatlan képhez `decision='rejected'` és üres számjegycímke kerüljön.

- [ ] **Step 4: Futtasd az API-teszteket**

Run: `.venv/bin/python -m pytest tests/test_web.py tests/test_pipeline.py -q`
Expected: PASS.

### Task 3: Kijelzőablak ellenőrzése a böngészős felületen

**Files:**
- Modify: `gasphoto/static/index.html`, `gasphoto/static/app.js`, `gasphoto/static/style.css`
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: Task 2 tanítópélda-végpontjai.
- Produces: a vásznon négypontos kijelölés, valamint `Jó ablak és érték`, `Ablak javítása`, `Olvashatatlan` döntés.

- [ ] **Step 1: Írj HTTP-szintű regressziós tesztet**

```python
assert 'training-example' in client.get('/static/app.js').text
assert 'window-approval' in client.get('/').text
```

- [ ] **Step 2: Futtasd és ellenőrizd a hibát**

Run: `.venv/bin/python -m pytest tests/test_web.py -q`
Expected: FAIL.

- [ ] **Step 3: Implementáld a kijelölő és döntési felületet**

A meglévő téglalap kijelölését négypontos kijelöléssé bővítsd, de első körben derékszögű téglalapot ments négy pontként. A jóváhagyás gomb csak akkor aktív, ha az ablak és a `00000.000` alakú érték is megvan. A felület egyértelműen jelezze, hogy a döntés tanító példa és a HA-feltöltés továbbra is külön művelet.

- [ ] **Step 4: Ellenőrizd böngészőben és tesztekkel**

Run: `.venv/bin/python -m pytest tests/test_web.py -q`
Expected: PASS; kézzel: kijelölés → érték → mentés → újratöltés után a keret látszik.

### Task 4: Reprodukálható adathalmaz-export és minőségkapu

**Files:**
- Create: `gasphoto/training.py`, `scripts/export_training.py`
- Modify: `gasphoto/store.py`
- Test: `tests/test_training.py`

**Interfaces:**
- Produces: `export_examples(store, destination, split_seed=...) -> ExportReport`
- Produces: YOLO `images/{train,val,test}`, `labels/{train,val,test}`, `manifest.json`.

- [ ] **Step 1: Írj hibázó exporttesztet**

```python
report = export_examples(store, tmp_path / 'dataset', split_seed=7)
assert report.usable == 40
assert (tmp_path / 'dataset' / 'manifest.json').exists()
```

- [ ] **Step 2: Futtasd a céltesztet**

Run: `.venv/bin/python -m pytest tests/test_training.py -q`
Expected: FAIL importhibával.

- [ ] **Step 3: Implementáld az exportot**

Írj teljes fotót és `register_window` YOLO-címkét. A split csoportosítása SHA-256-alapú, stabil és nem keveri ugyanazon nap közeli sorozatait. A manifest tartalmazza az eredeti fotóazonosítót, értéket és modelltől független címkéket. Az export álljon meg 40 jó példány alatt vagy tesztfelosztás nélkül.

- [ ] **Step 4: Futtasd a teljes exporttesztet**

Run: `.venv/bin/python -m pytest tests/test_training.py -q`
Expected: PASS.

### Task 5: Ablakdetektor és számjegyosztályozó futtatási adapter

**Files:**
- Create: `gasphoto/ml.py`
- Modify: `gasphoto/recognition.py`, `gasphoto/web.py`, `.env.example`
- Test: `tests/test_ml.py`, `tests/test_recognition.py`

**Interfaces:**
- Produces: `ModelRegistry.active() -> ModelVersion | None`
- Produces: `predict_register(path, model) -> {quad, confidence}` and `predict_digits(path, quad, model) -> proposal`

- [ ] **Step 1: Írj hibázó adapterteszteket**

```python
assert predict_register(path, missing_model)['quad'] is None
assert recognize_image(path, config={'mode':'trained'})['value'] is None
```

- [ ] **Step 2: Futtasd a teszteket**

Run: `.venv/bin/python -m pytest tests/test_ml.py tests/test_recognition.py -q`
Expected: FAIL importhibával.

- [ ] **Step 3: Implementáld az ONNX-futtatást és biztonságos visszaesést**

Az adapter csak `active` modellverziót tölthet be a `data/models/` könyvtárból. A hiányzó, sérült vagy alacsony bizalmú modell üres javaslatot ad. A nyolc pozíció, a számjegybizalmak, a modellazonosító és a megtalált négyszög bekerül a proposal JSON-ba. A régi Apple/Tesseract út megmarad kézi tartaléknak.

- [ ] **Step 4: Futtasd a célteszteket**

Run: `.venv/bin/python -m pytest tests/test_ml.py tests/test_recognition.py -q`
Expected: PASS.

### Task 6: Offline tanítás, értékelés és modellaktiválás

**Files:**
- Create: `scripts/train_window_detector.py`, `scripts/train_digit_classifier.py`, `scripts/evaluate_model.py`, `scripts/activate_model.py`
- Modify: `README.md`, `.gitignore`
- Test: `tests/test_training.py`, `tests/test_ml.py`

**Interfaces:**
- Consumes: Task 4 export és Task 5 modellregiszter.
- Produces: `candidate` modellverzió értékelési jelentéssel; `active` állapot csak átment modellhez.

- [ ] **Step 1: Írj hibázó aktiválási tesztet**

```python
with pytest.raises(ValueError, match='elkülönített teszt'):
    store.activate_model(candidate_id)
```

- [ ] **Step 2: Futtasd a tesztet**

Run: `.venv/bin/python -m pytest tests/test_training.py -q`
Expected: FAIL, mert nincs minőségi kapu.

- [ ] **Step 3: Implementáld a parancsokat**

A tanító parancs csak exportált adathalmazból készít jelölt YOLO ablakdetektort és a kijelző négyszögével normalizált, nyolc pozícióra osztott számjegyosztályozót, mindkettőt ONNX-be exportálja és menti a manifest-ujjlenyomatot. Az értékelő IoU-, teljes olvasat- és magas-bizalmú hibarátát ment. Az aktiváló csak 40 példány, elkülönített teszt és nulla magas-bizalmú téves javaslat mellett állítja aktívra a jelöltet.

- [ ] **Step 4: Futtasd a teljes ellenőrzést**

Run: `.venv/bin/python -m pytest -q && zsh -n start.command`
Expected: PASS.

- [ ] **Step 5: Dokumentáld a napi használatot**

A README-ben írd le: fotó → ablakjavítás → értékjóváhagyás → legalább 40 változatos címke → export → tanítás → elkülönített értékelés → aktiválás. Jelezd, hogy telepítendő ML-függőségek és az első tanítás külön, erőforrásigényes Mac-művelet.
