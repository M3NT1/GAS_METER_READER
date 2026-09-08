# Telefonfotós, tanuló gázóra-felismerés

## Cél

A meglévő Mac-es Gázóra Fotónapló a Xiaomi 15T Pro és iPhone 14 Pro Max eredeti fotóin, változó távolság és nézőszög mellett megkeresi a Sacofgas G4 mérő számlálóablakát. A kijelző öt fekete egész és három piros tizedes számjegyét csak javaslatként olvassa; emberi ellenőrzés nélkül sem a helyi napló, sem a Home Assistant nem kap új mérőértéket.

## Kiinduló adatok

- 103 helyi referenciafotó, közülük 94 már archiválva a `data/originals` könyvtárban.
- Minden kép ugyanazt a Sacofgas G4 mérőt mutatja.
- A fotók készítési ideje továbbra is kizárólag az eredeti EXIF-adatból származik.
- Az első tanító példák jóváhagyott kézi leolvasásokból készülnek; jelenleg nincs elfogadott érték.

## Választott megközelítés

Két, egymástól elválasztott modell fut:

1. **Számlálóablak-detektor.** YOLO-alapú, egyetlen `register_window` osztályú objektumdetektor a teljes telefonfotón. A cél az, hogy a mérő adattáblája, vonalkódja és gyári száma ne kerüljön a következő lépésbe.
2. **Kijelző-olvasó.** A megtalált ablakot négyszögkorrekció és egységes méret után nyolc pozícióra bontja. A pozíciókat egy saját, kis számjegyosztályozó olvassa; az első öt a fekete egész, az utolsó három a piros tizedes rész. A görgő átmeneti helyzetét az osztályozó alacsony bizalmi szinttel jelzi.

A számlálóablak kézi javítása adja az első modell címkéjét. A felhasználó által jóváhagyott teljes érték nyolc számjegycímkét ad a második modellnek. A javítás nem módosít automatikusan korábbi értéket és nem ír a Home Assistantba.

## Felhasználói folyamat

1. Az alkalmazás megjeleníti az automatikusan megtalált számlálóablakot zöld kerettel.
2. A felhasználó elfogadja vagy áthúzza a keretet a kizárólag fekete–piros görgősorra.
3. Az alkalmazás javaslatot ad és számjegyenként jelzi a bizalmi szintet.
4. A felhasználó jóváhagyja, javítja vagy elutasítja az értéket.
5. Jóváhagyáskor a rendszer változatlan eredeti fotóazonosítóval eltárolja a kivágást, a négyszög négy pontját, a javaslatot, a helyes értéket, a döntést és a modellverziót.
6. A jóváhagyott érték a már létező idő- és fogyasztási-plauzibilitási ellenőrzésen megy át. Csak utána kerül a meglévő küldési sorba.

## Adatmodell

Új SQLite táblák:

- `training_examples`: `photo_id`, `revision`, `window_quad_json`, `value_digits`, `decision`, `created_at`, `model_version`.
- `model_versions`: modellazonosító, típus (`window_detector` vagy `digit_classifier`), tanítóhalmaz-ujjlenyomat, mérőszámok, létrehozási idő, állapot (`candidate`, `active`, `rejected`).
- `model_evaluations`: modellazonosító, elkülönített fotóazonosító, detektált ablak IoU, teljes érték egyezése, számjegy-bizalmak és hibaok.

A `photos` tábla változatlan archívum- és EXIF-tárolási szerepe megmarad. A tanító rekordok csak jóváhagyott audit-revízióra mutathatnak.

## Tanítás és értékelés

- A rendszer képenként, időben elkülönített tanító/validációs/teszt csoportot képez; egymáshoz közeli, azonos fényviszonyú sorozat nem kerül külön csoportokba.
- Erősített változatok: legfeljebb 20 fok forgatás, perspektíva, méretezés, fényerő, kontraszt, enyhe életlenség és JPEG-tömörítés. A számlálóablaknak minden változatban teljesen látszania kell.
- Új modell csak akkor jelölt, ha legalább 40 jóváhagyott, változatos ablakcímke és 40 teljes érték áll rendelkezésre. A 103 régi kép címkézésére külön felület szolgál.
- Jelölt modell kizárólag elkülönített tesztképeken értékelhető. Aktív modellre váltás feltétele: a tesztképeken nincs hibás automatikus javaslat magas bizalommal; a teljes érték találati aránya és az ablakdetektálási eredmény nem romlik az aktív modellhez képest.
- Az első aktív modell csak javaslatot ad. Az automatikus jóváhagyás a projektben nem része ennek a változatnak.
- A hibás vagy bizonytalan képek értékes tanító példák; elutasított, olvashatatlan képhez nem készül számjegycímke.

## Biztonsági szabályok

- Csak a `register_window` által jelölt vagy a felhasználó által helyesbített területről készül javaslat.
- Pontosan öt egész és három tizedes pozíció szükséges. Bármely hiányzó, többszörös vagy küszöb alatti számjegy felülvizsgálatot kér.
- A javaslatot a meglévő időbeli szomszéd- és maximális fogyasztási szabályok is ellenőrzik.
- A modell sosem ír közvetlenül Home Assistantba, nem változtat EXIF-időpontot, és nem következtet hiányzó számjegyet fogyasztási trendből.
- Minden modell- és döntésváltozás auditálható, visszaváltható.

## Technológia és átállás

- Fejlesztés és tanítás: Python, Ultralytics YOLOv8, OpenCV, Pillow.
- Futás Macen: ONNX Runtime a számlálóablak-detektorhoz; a számjegyosztályozó ONNX formátumban. A meglévő Python/FastAPI alkalmazás hívja őket.
- A meglévő Apple Vision/Tesseract csak átmeneti, ellenőrző javaslat marad; nem tanító adatforrás.
- A modellfájlok a `data/models/` alatt, a tanító exportok a `data/training/` alatt élnek; mindkettő kizárt a forráskezelésből.
- Későbbi szerverre költözéskor változatlanul ezek a modellek és a SQLite-adatbázis költöznek.

## Elfogadási ellenőrzések

- Ferde, távoli és forgatott iPhone/Xiaomi-kép esetén a felület a teljes fotón mutatja a megtalált ablakot és engedi annak javítását.
- A javított keret és a jóváhagyott `01817.759` érték egyetlen, visszakereshető tanító példát hoz létre.
- A vonalkód, gyári szám és `Qt 0,600` felirat nem lehet számlálóablak vagy végleges javaslat.
- Külön tesztkészlet nélkül modell nem aktiválható.
- Modellhiba, hiányzó modell vagy alacsony bizalom esetén az alkalmazás változatlanul használható kézi leolvasással.
- A fotó EXIF-időpontja, a helyi audit és a Home Assistantba küldés viselkedése nem változik.
