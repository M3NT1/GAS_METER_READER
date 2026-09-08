# Ellenőrzési napló

Ezt a dokumentumot 2026-09-07-én frissítettük. A parancsokat a projekt gyökeréből kell futtatni.

## Automatikusan ismételhető ellenőrzések

```text
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q gasphoto
.venv/bin/python -m py_compile custom_components/gas_photo/ledger.py custom_components/gas_photo/sensor.py custom_components/gas_photo/__init__.py
.venv/bin/python scripts/package_ha.py --output /private/tmp/gasphoto-dist/gas_photo-custom-component.zip
```

Az utolsó fejlesztési futás eredménye: **72 teszt sikeres**, két harmadik féltől származó figyelmeztetéssel. A csomag tartalmazza a Python-fájlt, a kártyát, a szolgáltatásleírást és a manifestet.

## Amit izolált Home Assistantban ellenőriztünk

A projekt mellett egy ideiglenes, üres konfigurációban Home Assistant Core 2026.7.2 és Python 3.14.2 futott. A projekt `custom_components/gas_photo` könyvtárát bemásoltuk ebbe a tesztkonfigurációba; a meglévő Home Assistant példányhoz nem nyúltunk.

- Az integráció betöltődött, és regisztrálta a három szolgáltatást: `import_readings`, `get_readings`, `get_statistics`.
- A két szenzor létrejött.
- Egy admin felhasználói kontextusban importált tesztleolvasás változatlan, eredeti offsetes időponttal olvasható vissza.
- A Home Assistant elindítása és a Recorder sorának kiürülése után a `gas_photo:gas_main` sorban megjelent az órás `state=100.0`, `sum=0.0` rekord. A várt UTC óra `2026-01-01T11:00:00+00:00` volt.

Az üres tesztkörnyezetben több, a teljes Home Assistant disztribúcióhoz tartozó opcionális csomag hiányzott (például frontend és kamera függőségek); ezek hibái nem érintették a `gas_photo` betöltését és a Recorder-ellenőrzést.

## Képfeldolgozás

- Szintetikus, EXIF-es JPEG-en az orientáció és az EXIF-mentes OCR-kivágás ellenőrzött.
- A Mac Apple Vision adaptere a szintetikus `00123.456` alakot `123.456` értékként adta vissza, a gyári számot nem fogadta el mérőállásként.
- A rendelkezésre álló `cropped_test.jpg` képen nem született egyértelmű jelölt, ezért kézi ellenőrzést kért. Ez helyes biztonsági eredmény; nem jelent mérési pontossági garanciát.

## Még külön elvégzendő éles ellenőrzések

- A saját iPhone 14 Pro Max és Xiaomi 15T Pro eredeti képeivel legalább egy teljes feldolgozás és kézi jóváhagyás.
- Home Assistant mentés, kártya és az első tesztimport ellenőrzése a saját példányban.
- A régi Energy-források exportja és az esetleges átvezetés külön, jóváhagyott migrációként. Ez a projekt fejlesztési ellenőrzés közben nem módosított meglévő adatot.
- A Macről későbbi otthoni szerverre költözés csak a `data` könyvtár (SQLite + eredetik + previews) együtt mozgatásával történjen.
