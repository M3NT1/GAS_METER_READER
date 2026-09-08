#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
cd "$SCRIPT_DIR"

# A .env egyszerű KEY=ÉRTÉK sorait a helyi folyamat környezetébe tesszük.
# Így a Home Assistant és az opcionális vision-beállítások nem kerülnek a
# böngészőbe vagy a forráskódba.
if [[ -f "$SCRIPT_DIR/.env" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" == \#* ]] && continue
    [[ "$line" == [A-Za-z_][A-Za-z0-9_]*=* ]] && export "$line"
  done < "$SCRIPT_DIR/.env"
fi

if [[ ! -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
  print "A helyi Python környezet hiányzik: $SCRIPT_DIR/.venv"
  print "Telepítsd a README.md szerinti függőségeket, majd indítsd újra ezt a fájlt."
  exit 1
fi

exec "$SCRIPT_DIR/.venv/bin/python" -m gasphoto \
  --data-dir "$SCRIPT_DIR/data" \
  --port "${GASPHOTO_PORT:-8765}"
