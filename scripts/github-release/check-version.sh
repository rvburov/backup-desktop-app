#!/bin/bash
#
# Сверка номера версии в трех местах, где он записан:
#
#   backup_app/backend/constants.py             VERSION = "9.0.0"           <- источник правды
#   README.md                                   badge/version-9.0.0-blue    <- бейдж в шапке
#   scripts/github-release/release-history.md   ## [9.0.0] — 2026-10-06     <- описание версии
#
# Использование:
#
#   scripts/github-release/check-version.sh                   # сверить три места между собой
#   scripts/github-release/check-version.sh 9.0.1             # ...и с ожидаемой версией
#   scripts/github-release/check-version.sh --history-ready 9.0.1
#                                         # готова ли история релизов к выпуску 9.0.1
#                                         # (проверяется до правки версии)
#
# Один файл на все точки вызова: release.sh, job gate в .github/workflows/release.yml
# и release-test.sh. Если правила разложить по нескольким местам, они разойдутся.
#
# Код возврата: 0 — все сходится, 1 — есть расхождения (перечисляются все, а не только первое).
set -uo pipefail   # без -e: проверки должны выполниться все, а не оборваться на первой

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CONSTANTS="$ROOT/backup_app/backend/constants.py"
README="$ROOT/README.md"
HISTORY="$ROOT/scripts/github-release/release-history.md"
UNRELEASED="Не выпущено"

fail=0
err() { echo "  ✗ $1" >&2; fail=1; }

code_version() {
  sed -nE 's/^VERSION = "([^"]*)".*/\1/p' "$CONSTANTS" | head -n1
}

# Бейдж README: ![Version](https://img.shields.io/badge/version-9.0.0-blue.svg)
# Дефис у shields.io разделяет поля «подпись-значение-цвет», поэтому в версии дефисов нет
# и суффиксы вида 9.0.1-rc.1 не поддерживаются (см. проверку формата в release.sh).
readme_version() {
  sed -nE 's#.*badge/version-([^-]*)-blue.*#\1#p' "$README" | head -n1
}

# Есть ли в истории секция «## [имя]». Имя сравнивается как строка, а не как регулярное
# выражение: в номере версии точки, в «Не выпущено» кириллица. Символ \r в конце строки
# отбрасывается: на Windows файл может прийти с окончаниями строк CRLF.
section_exists() {
  awk -v head="## [$1]" '
    { line = $0; sub(/\r$/, "", line) }
    index(line, head) == 1 { found = 1; exit }
    END { exit !found }
  ' "$HISTORY"
}

# Есть ли в секции «## [имя]» хотя бы одна непустая строка до следующего «## [».
section_filled() {
  awk -v head="## [$1]" '
    { line = $0; sub(/\r$/, "", line) }
    index(line, head) == 1      { found = 1; next }
    found && line ~ /^## \[/    { exit }
    found && line ~ /[^ \t]/    { filled = 1; exit }
    END                         { exit !(found && filled) }
  ' "$HISTORY"
}

# ── Режим «готова ли история к выпуску» ──────────────────────────────────────
# Описание новой версии берется из одного из двух мест:
#   • секция «## [Не выпущено]», которую release.sh превратит в «## [версия] — дата»;
#   • уже заведенная секция «## [версия]» (так готовится первый выпуск текущей версии).
# Записи сразу в двух местах — ошибка: непонятно, какие из них относятся к версии.
if [ "${1:-}" = "--history-ready" ]; then
  want="${2:-}"
  [ -n "$want" ] || { echo "Использование: check-version.sh --history-ready <версия>" >&2; exit 1; }
  [ -f "$HISTORY" ] || { err "нет файла scripts/github-release/release-history.md"; exit 1; }
  if section_exists "$want"; then
    section_filled "$want" \
      || err "секция «## [${want}]» в release-history.md пустая — опишите, что изменилось"
    section_filled "$UNRELEASED" \
      && err "в «## [${UNRELEASED}]» есть записи, а секция «## [${want}]» уже заведена — перенесите их в нее"
  elif ! section_filled "$UNRELEASED"; then
    err "в release-history.md нет описания версии ${want}: опишите изменения в секции «## [${UNRELEASED}]»"
  fi
  exit $fail
fi

# ── Обычный режим: сверка трех мест ──────────────────────────────────────────
for f in "$CONSTANTS" "$README" "$HISTORY"; do
  [ -f "$f" ] || { echo "Нет файла: $f" >&2; exit 1; }
done

CODE_VER="$(code_version)"
README_VER="$(readme_version)"
WANT="${1:-$CODE_VER}"

[ -n "$CODE_VER" ]   || err "не удалось прочитать VERSION из backup_app/backend/constants.py"
[ -n "$README_VER" ] || err "не удалось прочитать бейдж версии из README.md"

[ "$CODE_VER" = "$WANT" ]   || err "constants.py: ${CODE_VER}, ожидалось ${WANT}"
[ "$README_VER" = "$WANT" ] || err "бейдж README.md: ${README_VER}, ожидалось ${WANT}"
section_filled "$WANT" \
  || err "release-history.md: нет непустой секции «## [${WANT}]»"

if [ $fail -eq 0 ]; then
  echo "✓ версия $WANT согласована: constants.py, README.md, release-history.md"
else
  echo "Версии разошлись. Источник правды — VERSION в backup_app/backend/constants.py." >&2
fi
exit $fail
