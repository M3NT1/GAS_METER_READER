# Számlálóolvasó modell terve

## Cél

A helyi alkalmazás a képen megtalálja a fekete–piros görgős számlálósort, majd egy külön modell nyolc számjegyként kiolvassa az értéket. Minden eredmény emberi ellenőrzésre vár; Home Assistant feltöltés csak kézi jóváhagyás után történik.

## Állapotok

- `needs_review`: nincs használható gépi eredmény.
- `position_identified`: a számlálósor helye ismert, érték még nincs.
- `counter_recognized`: a nyolc számjegy kiolvasható, az érték a szerkeszthető mezőben jelenik meg.
- A meglévő `pending_sync` és `synced` változatlan.

## Tanítóadat és modellek

A jóváhagyott képhez tárolt számlálósor-keret és a kézzel ellenőrzött érték két külön tanítóhalmazt ad. A keretmodell egy YOLO detektor. A számlálómodell a keretből azonos szélességű nyolc görgőképet készít, és 0–9 közötti számjegyosztályozót tanít. Egy fotó minden számjegye ugyanabba a tanító-, validációs vagy tesztcsoportba kerül, így nincs adatszivárgás.

## Felület

Két tanítási kártya és két indítógomb jelenik meg. Mindkettő külön háttérfolyamatot, folyamatjelzőt és naplóablakot használ. A leolvasásnál a megtalált pozíció zöld kerettel, a felismerés pedig szerkeszthető mérőállásként látható.

## Biztonsági korlátok

Az olvasó csak akkor ad értéket, ha mind a nyolc számjegy biztonsága eléri a küszöböt. Minden egyéb eset `position_identified` vagy `needs_review`; nincs automatikus jóváhagyás és nincs automatikus HA-feltöltés.
