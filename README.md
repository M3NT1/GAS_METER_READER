# Gázóra-leolvasások Home Assistanthez

Macen futó, helyi feldolgozó alkalmazás gázóra-fotókhoz. Az eredeti HEIC/JPEG képet az iPhone 14 Pro Max vagy Xiaomi 15T Pro készítheti; a rendszer a kép EXIF metaadatából olvassa ki a fotó tényleges készítési idejét, majd kézi jóváhagyás után küldi a mérőállást a Home Assistantnak.

## Mit tud?

- változatlan eredeti kép és SHA-256 azonosítóval védett archívum;
- pontos, időzónás `DateTimeOriginal` időpont, másodperctörttel együtt;
- helyi számlálóablak-keresés betanított YOLO-modellel;
- a kijelölt ablakon belül nyolc görgő külön felismerése (5 fekete egész + 3 piros tizedes);
- kézi kijelölő nagyítóval és automatikusan előtöltött mérőállás-mezővel;
- kötelező emberi ellenőrzés: a felismerés javaslat, nem automatikus mérési igazolás;
- visszajelzések: `Ellenőrzésre vár`, `Pozíció azonosítva`, `Számláló felismerve`, `Feltöltésre vár`, `Szinkronizált`;
- külön tanítási vezérlés a keretező és a számlálómodellhez, élő naplóval és párbeszédablakos folyamatjelzővel;
- a piros tizedes görgők alacsonyabb elfogadási küszöbe, miközben a fekete egész rész szigorúbb ellenőrzést kap;
- kép elvetése megerősítő dialógussal (már jóváhagyott vagy szinkronizált leolvasás nem törölhető);
- Home Assistantba újrapróbálható feltöltési várólista és pontos leolvasási napló;
- a kezdő nullákat a felületen és a Home Assistantba küldés előtt eltávolítja (például `01716.576` → `1716.576`).

Az Energy nézet órás Recorder-statisztikát kap. A fotó pontos időpontja a `gas_photo` naplóban marad; a két fotó közötti napi fogyasztást a rendszer nem találja ki.

## Gyors indítás macOS-en

A támogatott fejlesztői környezet Python 3.12 vagy újabb.

```text
cd /Users/kasnyiklaszlo/_DEV/_GAZORA_DIGITALIZALAS
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[test]"
```

A gépi tanításhoz és a helyi modell-alapú felismeréshez telepítsd a gépen használt ML-csomagokat is:

```text
.venv/bin/python -m pip install ultralytics onnxruntime opencv-python
```

Másold a mintafájlt `.env` néven, és csak a szükséges beállításokat töltsd ki:

```text
cp .env.example .env
```

Helyi felismeréshez a `GASPHOTO_OCR=local` az alapérték. Home Assistant-feltöltéshez add meg a `HA_URL` és `HA_TOKEN` értékét; a token csak a Macen marad, és nem kerül a böngészőbe vagy a GitHubra.

Indítás:

```text
./start.command
```

Nyisd meg a `http://127.0.0.1:8765` címet. A **Beállítások** nézetben választható ki a bemeneti mappa; alapértelmezésben ez `data/inbox`. Az alkalmazás 20 másodpercenként átnézi a mappát, a **Mappa átnézése** gomb pedig azonnali ellenőrzést indít. Az eredeti képeket másold ide, ne szerkesztett exportokat.

## Napi használat

1. Másold a telefonról az eredeti `.HEIC`, `.HEIF`, `.JPG` vagy `.JPEG` fájlokat a bemeneti mappába.
2. Válaszd ki a képet a **Leolvasások** nézetben.
3. Nyomd meg az **Újraolvasás** gombot. A keretező modell először megkeresi a számlálóablakot, majd a számlálómodell a kereten belüli nyolc görgőt olvassa.
4. A zöld kijelölést ellenőrizd a jobb felső nagyítóval. Ha kell, húzd át pontosan a fekete és piros számjegysorra.
5. Ellenőrizd vagy írd felül a mérőállást és a fotó készítési idejét.
6. Nyomd meg az **Ellenőriztem, mentés** gombot. A kijelölés és a kézzel megerősített számérték tanítópéldaként is elmentődik.
7. A jóváhagyott rekord **Feltöltésre vár** állapotba kerül. A felső **Feltöltés a HA-ba** gomb küldi el a várólistát.

Ha a kép nem használható, a **Kép elvetése** gomb külön megerősítést kér, majd törli a nem jóváhagyott rekordot, archívumot és előnézetet.

## Saját modell tanítása

A jóváhagyáskor a rendszer két dolgot ment: a számlálóablak normalizált négyszögét és a kézzel ellenőrzött nyolc számjegyet. Ezekből készül a két külön tanítóhalmaz.

- **Keretező tanítása**: azt tanulja meg, hol van a teljes számjegysor a fotón.
- **Számláló tanítása**: a kijelölt ablakot nyolc görgőre osztja, és görgőnként a `0`–`9` osztályt tanulja.

Mindkét tanítás a **Beállítások** nézetben külön gombbal indítható. Legalább 40 jóváhagyott, kijelölt fotó szükséges. A folyamatjelző és a részletes napló a tanítási dialógusban látható; a tanítás háttérszálon fut, ezért az oldal használható marad.

A tanítóscript 80/10/10 arányú tanító-, validációs- és tesztfelosztást használ. A számlálómodell csak akkor aktiválódik, ha a külön tesztkészleten legalább 90% top-1 pontosságot ér el. Újabb jóváhagyott képekkel a következő tanítás új modellverziót készít; ez nem módosítja visszamenőleg a korábbi leolvasásokat.

Felismert, de bizonytalan görgő esetén a javaslat és a pozíciók megjelennek a képernyőn. A fekete egész számjegyek alap-küszöbe 75%, a piros tizedeseké 50%; az alacsonyabb piros biztonság külön figyelmeztetést kap. A végső érték mindig kézzel ellenőrizhető.

## Home Assistant integráció

A mellékelt egyedi komponens csomagolása:

```text
.venv/bin/python scripts/package_ha.py
```

A létrejött `dist/gas_photo-custom-component.zip` tartalmát másold a Home Assistant `/config` könyvtárába úgy, hogy a végső útvonal `/config/custom_components/gas_photo/...` legyen. A `configuration.yaml` fájlban:

```yaml
gas_photo:
  max_m3_per_hour: 6
```

A `max_m3_per_hour` a két szomszédos, jóváhagyott leolvasás közötti fizikailag megengedett maximum. Állítsd a saját mérő és fűtési rendszeredhez.

Indítsd újra a Home Assistantot, majd a Mac alkalmazásban a **HA-kapcsolat** gombbal ellenőrizd a kapcsolatot. A komponens szolgáltatásai:

- `gas_photo.import_readings` – pontos, offsetes időponttal mentett leolvasás;
- `gas_photo.get_readings` – a pontos napló visszaolvasása;
- `gas_photo.get_statistics` – a Recorder tényleges órás statisztikáinak ellenőrzése.

A `queued` válasz a tartós naplózást és a Home Assistant feldolgozási sorába helyezést jelenti; a Recorder-eredményt a `get_statistics` olvasásával kell ellenőrizni. A komponens nem módosítja a korábbi Energy-forrásokat.

## Adatok és adatvédelem

Futás közben a `data/` könyvtárban keletkeznek az eredetik, előnézetek, SQLite-napló, tanítóhalmazok és modellek. Ezek szándékosan ki vannak zárva a Gitből, mert személyes fotókat, helyi útvonalakat és nagy bináris fájlokat tartalmazhatnak. A `.env` és a Home Assistant-token szintén kizárt.

A távoli vision/OCR mód csak külön bekapcsolva használható; ilyenkor kizárólag a kijelölt számláló-kivágás kerül továbbításra, EXIF nélkül. Alapértelmezésben a feldolgozás helyi.

## Fejlesztés és ellenőrzés

```text
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q gasphoto
.venv/bin/python -m py_compile custom_components/gas_photo/ledger.py custom_components/gas_photo/sensor.py custom_components/gas_photo/__init__.py
```

A részletes integrációs ellenőrzési napló a [`docs/verification.md`](docs/verification.md) fájlban, a Home Assistant komponens dokumentációja pedig a [`custom_components/gas_photo/README.md`](custom_components/gas_photo/README.md) fájlban található.

## Fontos korlátok

- A modell egy konkrét mérő, fotózási környezet és kijelölési szokás alapján tanul; más mérőn új tanítóhalmaz szükséges.
- A felismerés nem helyettesíti az emberi ellenőrzést.
- A mérőállás nem csökkenhet, és a konfigurált fogyasztási maximumot meghaladó ugrás jóváhagyása elutasításra kerül.
- A pontos fotótörténet és a Recorder-statisztika külön fogalom; a köztes órák és napok értékeit a rendszer nem interpolálja.
