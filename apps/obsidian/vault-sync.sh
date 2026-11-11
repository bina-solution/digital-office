#!/bin/sh
# vault-sync.sh — carry `.generated/vault/` into the office's ONE vault folder (DGO-1642).
#
#   vault-sync.sh --generated <dir> --vault <dir>
#
# The compiler renders the vault; this puts it in place. It runs at every `bbox run`
# (apps/obsidian/hooks/prepare) and on demand (`./bbox obsidian sync`), so its behaviour is a rule and
# not a convenience. Four promises, in the order they matter:
#
#   1. A NOTE A PERSON EDITED IS NEVER OVERWRITTEN. Left alone, reported (`skip-edited`), printed in the
#      summary. "The compiler silently ate my correction" is the one failure this script exists to
#      prevent, and it is decided by content, not by mtime or guesswork.
#   2. NOTHING IS EVER DELETED. A note whose source is gone stays in the vault and is listed in
#      `.office/stale.txt` — knowledge that is old beats knowledge that vanished.
#   3. IT WRITES ONLY WHAT CHANGED. A second pass with an unchanged render writes zero files, which is
#      what makes running it at every bring-up safe.
#   4. THE PERSON'S AREA IS THEIRS. `Notes/` and `Operatives/` are seeded once (an empty `Notes/`, and
#      the operative template) and never written again.
#
# The state it compares against is `<vault>/.office/state.txt`: `<sha256><TAB><note path>`, the sha of
# what the LAST render produced for that note. Without it (a vault copied from elsewhere, or a lost
# `.office/`) the script cannot tell "the person changed this" from "the render changed", so it refuses
# to overwrite and says so — the safe answer, since it is recoverable by deleting the note.
#
# POSIX sh + coreutils only: it runs inside alpine with the vault volume mounted, so there is no python
# and no jq, and the file names are Hebrew with spaces (hence TAB as the separator, never a space).
set -u

GEN=""
VAULT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --generated) GEN="${2:-}"; shift 2 ;;
    --vault)     VAULT="${2:-}"; shift 2 ;;
    -h|--help)   sed -n 's/^# \{0,1\}//p' "$0" | head -30; exit 0 ;;
    *) echo "vault-sync: unknown argument '$1'" >&2; exit 2 ;;
  esac
done
[ -n "$GEN" ] && [ -n "$VAULT" ] || { echo "usage: vault-sync.sh --generated DIR --vault DIR" >&2; exit 2; }

summary() { echo "summary wrote=$1 unchanged=$2 edited=$3 stale=$4"; }

if [ ! -d "$GEN" ] || [ ! -f "$GEN/.vault-manifest.json" ]; then
  echo "vault-sync: no manifest in '$GEN' — nothing was rendered, so nothing is written"
  summary 0 0 0 0
  exit 0
fi

mkdir -p "$VAULT/.office" || { echo "vault-sync: cannot create '$VAULT/.office'" >&2; exit 1; }
STATE="$VAULT/.office/state.txt"
[ -f "$STATE" ] || : > "$STATE"
NEW_STATE="$(mktemp)"
LIST="$(mktemp)"
STALE_NEW="$(mktemp)"
trap 'rm -f "$NEW_STATE" "$LIST" "$STALE_NEW"' EXIT INT TERM

# Every rendered note, relative to the generated root, sorted so the run is reproducible.
( cd "$GEN" && find . -type f ! -name '.vault-manifest.json' -print | sed 's|^\./||' | LC_ALL=C sort ) > "$LIST"

wrote=0; unchanged=0; edited=0; stale=0
TAB="$(printf '\t')"

prev_sha() {  # the sha of what the last render produced for "$1", or empty
  awk -F'\t' -v p="$1" '$2==p{print $1; exit}' "$STATE"
}

while IFS= read -r rel; do
  [ -n "$rel" ] || continue
  src="$GEN/$rel"
  dst="$VAULT/$rel"
  want="$(sha256sum "$src" | cut -d' ' -f1)"
  prev="$(prev_sha "$rel")"
  printf '%s\t%s\n' "$want" "$rel" >> "$NEW_STATE"

  if [ ! -f "$dst" ]; then
    mkdir -p "$(dirname "$dst")"
    cp "$src" "$dst" && { wrote=$((wrote + 1)); echo "write $rel"; }
    continue
  fi
  have="$(sha256sum "$dst" | cut -d' ' -f1)"
  if [ "$have" = "$want" ]; then
    unchanged=$((unchanged + 1))
  elif [ -n "$prev" ] && [ "$have" = "$prev" ]; then
    cp "$src" "$dst" && { wrote=$((wrote + 1)); echo "write $rel"; }
  else
    edited=$((edited + 1))
    echo "skip-edited $rel"
  fi
done < "$LIST"

# — what the vault has and the render no longer does: keep it, say it.
if [ -s "$STATE" ]; then
  while IFS="$TAB" read -r sha rel; do
    [ -n "${rel:-}" ] || continue
    grep -Fqx -- "$rel" "$LIST" && continue
    stale=$((stale + 1))
    printf '%s\t%s\n' "$sha" "$rel" >> "$NEW_STATE"
    printf '%s\n' "$rel" >> "$STALE_NEW"
    echo "stale $rel"
  done < "$STATE"
fi
STALE_LIST="$VAULT/.office/stale.txt"
if ! cmp -s "$STALE_NEW" "$STALE_LIST" 2>/dev/null; then
  LC_ALL=C sort -u "$STALE_NEW" > "$STALE_LIST"
fi
LC_ALL=C sort "$NEW_STATE" > "$NEW_STATE.sorted" && mv "$NEW_STATE.sorted" "$NEW_STATE"
if ! cmp -s "$NEW_STATE" "$STATE" 2>/dev/null; then
  mv "$NEW_STATE" "$STATE"
fi

# — the person's own area: seeded once, then theirs. Never rewritten.
mkdir -p "$VAULT/Notes" "$VAULT/Operatives"
if [ ! -f "$VAULT/Notes/README.md" ]; then
  cat > "$VAULT/Notes/README.md" <<'NOTE'
# הערות — המקום שלך

כל מה שתכתבו כאן נשאר שלכם: הסינכרון של הלשכה לא נוגע בתיקייה הזו, לא מוחק ולא משכתב.

מה שכן נכתב אוטומטית יושב ב-`Office/`, `Architecture/`, `Apps/` ו-`Herd/` (לשכה של העסק בלבד),
וכל פתק כזה מתחיל ב-`generated: true` ונוקב במקור שלו. רוצים לשנות פתק כזה? ערכו את המקור בריפו —
הפתק כאן ייווצר מחדש בכל `bbox run`.
NOTE
fi
if [ ! -f "$VAULT/Operatives/README.md" ]; then
  cat > "$VAULT/Operatives/README.md" <<'NOTE'
# Operatives — הזיכרון של העבודות החוזרות

פעולה שמתבצעת שוב ושוב בלשכה (עיבוד פגישה, בדיקת דומיין, סקירת אבטחה, הוספת אפליקציה) נשמרת כאן
כפתק אחד, ולפני שמריצים אותה קוראים אותה. זהו הזיכרון של הסוכן, והוא היחיד שהוא כותב בו בלי לשאול.

## פתק חדש — לפי התבנית הזו

```
# <שם הפעולה>

## מתי מריצים
משפט אחד: מה מבקשים ממני כשהיא רלוונטית.

## שלבים
1. פקודה מדויקת, עם המשתנים שלה.
2. …

## מה נחשב הצלחה
הפלט המדויק שמראה שזה עבד — לא "עבד".

## מאורות
מה כבר נכשל כאן, ואיך מזהים את זה שוב.

## Run log
- YYYY-MM-DD — מה רץ, ומה יצא.
```

כלל אחד: שלבים ופקודות, אף פעם לא סיפור, ואף פעם לא סוד. פתק קיים מתקנים במקום; לא כותבים אחד שני.
NOTE
fi

summary "$wrote" "$unchanged" "$edited" "$stale"
