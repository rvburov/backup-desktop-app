#!/bin/bash
#
# Выпуск релиза BackupApp на GitHub: локальная половина процесса.
#
#   scripts/github-release/release.sh 9.0.1                 # выпустить версию 9.0.1
#   scripts/github-release/release.sh 9.0.1 --dry-run       # только проверки, ничего не менять
#   scripts/github-release/release.sh 9.0.1 --skip-tests    # без прогона тестов
#   scripts/github-release/release.sh 9.0.1 --allow-dirty   # разрешить незакоммиченные правки
#
# Что делает: проверяет предусловия → меняет VERSION в backup_app/backend/constants.py и бейдж
# в README.md → превращает секцию «## [Не выпущено]» истории релизов в «## [9.0.1] — дата» →
# коммитит «Выпуск версии 9.0.1» → ставит тег v9.0.1 → отправляет master и тег на GitHub.
# Собирает и публикует уже GitHub: .github/workflows/release.yml ловит push тега.
# Обычный git push релиз не запускает.
#
# Скрипт ничего не собирает и не требует gh: нужен git, а для тестов Python с пакетами
# из requirements.txt (venv в корне проекта находится сам). Подробно: docs/README_RELEASE.md
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HERE="$(cd "$(dirname "$0")" && pwd)"
# Пути относительно корня проекта: скрипт работает из корня, так их одинаково понимает git
# на всех системах, включая Git Bash на Windows.
CONSTANTS="backup_app/backend/constants.py"
README="README.md"
HISTORY="scripts/github-release/release-history.md"
MAIN_BRANCH="master"
UNRELEASED="Не выпущено"
REPO_URL="https://github.com/rvburov/backup-desktop-app"

VERSION=""
DRY_RUN=0
SKIP_TESTS=0
ALLOW_DIRTY=0

for arg in "$@"; do
  case "$arg" in
    --dry-run)     DRY_RUN=1 ;;
    --skip-tests)  SKIP_TESTS=1 ;;
    --allow-dirty) ALLOW_DIRTY=1 ;;
    -h|--help)     sed -n '2,17p' "$0"; exit 0 ;;
    -*)            echo "Неизвестный ключ: $arg" >&2; exit 1 ;;
    *)             [ -z "$VERSION" ] && VERSION="$arg" || { echo "Лишний аргумент: $arg" >&2; exit 1; } ;;
  esac
done

die()  { echo "✗ $1" >&2; exit 1; }
info() { echo "  $1"; }
step() { echo "→ $1"; }

# Перезапись файла через временный: у sed -i разный синтаксис в GNU и BSD.
# cat > файл, а не mv: так у файла остаются прежние права.
replace_with() { cat "$1" > "$2" && rm -f "$1"; }

# Сравнение версий X.Y.Z покомпонентно: печатает -1, 0 или 1.
ver_cmp() {
  local IFS=.
  # shellcheck disable=SC2206
  local a=($1) b=($2) i
  for i in 0 1 2; do
    if (( 10#${a[i]} > 10#${b[i]} )); then echo 1; return; fi
    if (( 10#${a[i]} < 10#${b[i]} )); then echo -1; return; fi
  done
  echo 0
}

# Python для тестов: переменная PYTHON, venv проекта, затем python3 и python из PATH.
find_python() {
  local candidate
  for candidate in "${PYTHON:-}" "$ROOT/venv/Scripts/python.exe" "$ROOT/venv/bin/python" \
                   "$ROOT/.venv/Scripts/python.exe" "$ROOT/.venv/bin/python" python3 python; do
    [ -n "$candidate" ] || continue
    if command -v "$candidate" > /dev/null 2>&1; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

[ -n "$VERSION" ] || die "не указана версия. Пример: scripts/github-release/release.sh 9.0.1"

# ── 1. Формат версии ──────────────────────────────────────────────────────────
# Только X.Y.Z. Суффиксы вида 9.0.1-rc.1 запрещены: у shields.io дефис разделяет поля
# бейджа, и «version-9.0.1-rc.1-blue» распался бы на версию 9.0.1 и цвет rc.1.
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] \
  || die "версия «${VERSION}» не в формате X.Y.Z (суффиксы вида -rc.1 не поддерживаются)"

cd "$ROOT" || die "не удалось перейти в $ROOT"

# ── 2. Ветка и чистота рабочего дерева ────────────────────────────────────────
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
[ "$BRANCH" = "$MAIN_BRANCH" ] || die "текущая ветка «${BRANCH}», релизы выпускаются из ${MAIN_BRANCH}"

if [ -n "$(git status --porcelain)" ]; then
  if [ $ALLOW_DIRTY -eq 1 ]; then
    echo "⚠ рабочее дерево не чистое, продолжаю из-за --allow-dirty"
  else
    git status --short >&2
    die "рабочее дерево не чистое: закоммитьте или спрячьте правки"
  fi
fi

# ── 3. Синхронность с origin ──────────────────────────────────────────────────
# Сеть может быть недоступна. В настоящем выпуске это отказ: без сверки с origin легко
# поставить тег на устаревший коммит. В --dry-run только предупреждение.
NET_OK=1
git fetch --quiet origin "$MAIN_BRANCH" --tags 2>/dev/null || NET_OK=0

if [ $NET_OK -eq 1 ]; then
  LOCAL="$(git rev-parse HEAD)"
  REMOTE="$(git rev-parse "origin/$MAIN_BRANCH")"
  if [ "$LOCAL" != "$REMOTE" ]; then
    if git merge-base --is-ancestor "$REMOTE" "$LOCAL"; then
      die "есть неотправленные коммиты: сначала git push origin ${MAIN_BRANCH} и зеленые тесты на GitHub"
    else
      die "локальная ${MAIN_BRANCH} разошлась с origin/${MAIN_BRANCH}: сначала git pull"
    fi
  fi
elif [ $DRY_RUN -eq 1 ]; then
  echo "⚠ origin недоступен: проверки против GitHub пропущены (--dry-run)"
else
  die "не удалось связаться с origin: проверьте сеть и доступ к $REPO_URL"
fi

# ── 4. Тег свободен ───────────────────────────────────────────────────────────
TAG="v$VERSION"
git rev-parse -q --verify "refs/tags/$TAG" > /dev/null \
  && die "тег $TAG уже существует. Пересобрать релиз, не двигая тег, можно на вкладке
    Actions → Release → Run workflow с параметром tag=$TAG"

if [ $NET_OK -eq 1 ] && git ls-remote --exit-code --tags origin "refs/tags/$TAG" > /dev/null 2>&1; then
  die "тег $TAG уже есть на GitHub: версия занята"
fi

# ── 5. Версия не меньше текущей ───────────────────────────────────────────────
# Равная допускается: так выпускается версия, которая уже записана в коде, но еще не
# выпускалась (тег свободен, это проверено выше). Так выходит первый релиз.
CURRENT="$(sed -nE 's/^VERSION = "([^"]*)".*/\1/p' "$CONSTANTS" | head -n1)"
[[ "$CURRENT" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "не удалось прочитать VERSION из $CONSTANTS"
[ "$(ver_cmp "$VERSION" "$CURRENT")" -ge 0 ] || die "версия $VERSION меньше текущей $CURRENT"

# ── 6. Согласованность и описание версии ──────────────────────────────────────
# Скрипты вызываются через bash, а не напрямую: так не важно, сохранился ли у файла бит запуска.
bash "$HERE/check-version.sh" > /dev/null \
  || die "текущее состояние рассогласовано: запустите scripts/github-release/check-version.sh"

bash "$HERE/check-version.sh" --history-ready "$VERSION" || die "история релизов не готова к выпуску.
    Опишите изменения в секции «## [${UNRELEASED}]» файла $HISTORY."

# Откуда берется описание: из уже заведенной секции версии или из «Не выпущено».
if awk -v head="## [$VERSION]" '
     { line = $0; sub(/\r$/, "", line) }
     index(line, head) == 1 { found = 1; exit }
     END { exit !found }
   ' "$HISTORY"; then
  HISTORY_FROM="$VERSION"
else
  HISTORY_FROM="$UNRELEASED"
fi

# ── 7. Быстрая проверка кода ──────────────────────────────────────────────────
if [ $SKIP_TESTS -eq 0 ]; then
  PY="$(find_python)" \
    || die "не найден Python для тестов: создайте venv и поставьте requirements.txt или запустите с --skip-tests"
  "$PY" -m pytest --version > /dev/null 2>&1 \
    || die "в $PY нет pytest: pip install -r requirements.txt или запуск с --skip-tests"
  step "pyflakes и pytest ($PY)"
  "$PY" -m pyflakes backup_app tests backup-app.py || die "pyflakes нашел ошибки, релиз отменен"
  QT_QPA_PLATFORM=offscreen PYTHONUTF8=1 "$PY" -m pytest || die "тесты не прошли, релиз отменен"
else
  echo "⚠ тесты пропущены (--skip-tests)"
fi

# ── 8. План и подтверждение ───────────────────────────────────────────────────
TODAY="$(date +%F)"
NEW_HEAD="## [$VERSION] — $TODAY"
echo
echo "Релиз BackupApp $VERSION (сейчас в коде $CURRENT)"
info "constants.py        VERSION → $VERSION"
info "README.md           бейдж → version-$VERSION-blue"
info "release-history.md  «## [${HISTORY_FROM}]» → «${NEW_HEAD}»"
info "коммит              Выпуск версии $VERSION"
info "тег                 $TAG"
info "push                origin $MAIN_BRANCH, затем origin $TAG"
info "дальше              GitHub соберет Windows, macOS (Apple Silicon и Intel), Linux и опубликует релиз"
echo

if [ $DRY_RUN -eq 1 ]; then
  echo "✓ проверки пройдены. Это --dry-run: ни один файл не изменен."
  exit 0
fi

read -r -p "Выпустить $TAG? [y/N] " answer
case "$answer" in
  y|Y|yes|д|Д|да|Да) ;;
  *) echo "Отменено."; exit 0 ;;
esac

# ── 9. Правка версии ──────────────────────────────────────────────────────────
step "правка версии"
tmp="$(mktemp)"
sed -E "s/^VERSION = \"[^\"]*\"/VERSION = \"${VERSION}\"/" "$CONSTANTS" > "$tmp" && replace_with "$tmp" "$CONSTANTS"
tmp="$(mktemp)"
sed -E "s#badge/version-[^-]*-blue#badge/version-${VERSION}-blue#" "$README" > "$tmp" && replace_with "$tmp" "$README"

# Заголовок секции в истории. \r в конце строки сохраняется: на Windows файл может быть в CRLF.
tmp="$(mktemp)"
if [ "$HISTORY_FROM" = "$UNRELEASED" ]; then
  # «## [Не выпущено]» становится «## [версия] — дата», а над ней появляется новая пустая
  # «## [Не выпущено]» для следующих правок.
  awk -v head="## [$UNRELEASED]" -v new="$NEW_HEAD" '
    { line = $0; cr = ""; if (sub(/\r$/, "", line)) cr = "\r" }
    !done && index(line, head) == 1 { print head cr; print cr; print new cr; done = 1; next }
    { print }
  ' "$HISTORY" > "$tmp" && replace_with "$tmp" "$HISTORY"
else
  # Секция версии уже заведена: в ее заголовок ставится дата.
  awk -v head="## [$VERSION]" -v new="$NEW_HEAD" '
    { line = $0; cr = ""; if (sub(/\r$/, "", line)) cr = "\r" }
    !done && index(line, head) == 1 { print new cr; done = 1; next }
    { print }
  ' "$HISTORY" > "$tmp" && replace_with "$tmp" "$HISTORY"
fi

bash "$HERE/check-version.sh" "$VERSION" || die "после правки версии остались расхождения"

# ── 10. Коммит, тег, отправка ─────────────────────────────────────────────────
step "коммит и тег"
git add -- "$CONSTANTS" "$README" "$HISTORY" || die "git add не сработал"
if git diff --cached --quiet; then
  info "файлы уже содержат версию $VERSION, тег ставится на текущий коммит"
else
  git commit -q -m "Выпуск версии $VERSION" || die "коммит не создан"
fi
git tag -a "$TAG" -m "BackupApp $VERSION" || die "тег $TAG не создан"

# Порядок важен: если push ветки отклонен (кто-то опередил), тег на GitHub не уедет,
# и версию можно перевыпустить, ничего не разбирая на сервере.
step "push origin $MAIN_BRANCH"
git push --quiet origin "$MAIN_BRANCH" || die "push ветки отклонен. Тег $TAG создан локально; после
    git pull --rebase повторите: git push origin $MAIN_BRANCH && git push origin $TAG"

step "push origin $TAG"
git push --quiet origin "$TAG" || die "push тега отклонен, отправьте вручную: git push origin $TAG"

echo
echo "✓ $TAG отправлен. Сборка идет на GitHub:"
echo "  $REPO_URL/actions"
echo "  $REPO_URL/releases/tag/$TAG   (появится примерно через 15 минут)"
