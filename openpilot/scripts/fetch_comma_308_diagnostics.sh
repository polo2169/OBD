#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TARGET="${1:-}"
if [[ -z "$TARGET" || ! "$TARGET" =~ ^[a-zA-Z0-9.:_-]+$ ]]; then
  echo "Usage : $0 [adresse IP ou nom du comma]" >&2
  exit 2
fi
KNOWN_HOSTS="$ROOT/data/runtime/comma_known_hosts"
if [[ ! -f "$KNOWN_HOSTS" ]]; then
  echo "Clé d'hôte du comma absente : $KNOWN_HOSTS" >&2
  exit 1
fi
OUT="$ROOT/data/diagnostics/comma"
mkdir -p "$OUT"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ARCHIVE="$OUT/308-$STAMP-$$.tar.gz"
PARTIAL="$ARCHIVE.partial"
trap 'rm -f "$PARTIAL"' EXIT
echo "Récupération des journaux locaux de ${TARGET}…"
ssh -F /dev/null -i "$HOME/.ssh/id_ed25519" \
  -o UseKeychain=yes -o BatchMode=yes -o IdentitiesOnly=yes -o ForwardAgent=no \
  -o HostKeyAlias=172.19.159.205 \
  -o ConnectTimeout=8 -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$KNOWN_HOSTS" \
  "comma@$TARGET" '/usr/local/venv/bin/python -' > "$PARTIAL" <<'PY'
from contextlib import ExitStack
from pathlib import Path
import re
import sys
import tarfile

root = Path('/data/psa-diagnostics')
assert root.is_dir(), 'Pas de collecte /data/psa-diagnostics sur le comma'
with ExitStack() as stack:
    opened = []
    for path in sorted(root.iterdir()):
        if path.is_symlink() or not path.is_file():
            continue
        if path.name != 'status.json' and not re.fullmatch(r'capture-\d{8,}\.(rlog|json)', path.name):
            continue
        try:
            stream = stack.enter_context(path.open('rb'))
        except FileNotFoundError:
            continue  # Retention rotated this segment before it was opened.
        opened.append((path.name, stream))
    assert any(name.endswith('.rlog') for name, _ in opened), 'Aucun journal enregistré'
    # Open descriptors keep old segments readable if recording rotates them.
    # gettarinfo fixes each length; appends cannot make the archive inconsistent.
    with tarfile.open(fileobj=sys.stdout.buffer, mode='w|gz') as archive:
        for name, stream in opened:
            info = archive.gettarinfo(fileobj=stream, arcname='psa-diagnostics/' + name)
            info.uid = info.gid = 0
            info.uname = info.gname = ''
            archive.addfile(info, stream)
PY
gzip -t "$PARTIAL"
mv "$PARTIAL" "$ARCHIVE"
echo "Archive locale : $ARCHIVE"
echo "Les originaux restent sur le comma. Les journaux CAN peuvent contenir des données du véhicule."
echo "Pour préparer un envoi borné avec le code correspondant :"
echo "python3 openpilot/tools/export_t9_dataset.py '$ARCHIVE' --segments 4 --output 'data/diagnostics/comma/t9-dataset-$STAMP.tar.gz'"
