#!/bin/bash
#
# Тесты скриптов выпуска. Нужны только bash и git: Python, сеть и gh не требуются.
#
#   scripts/github-release/release-test.sh
#
# release.sh проверяется по-настоящему, вплоть до коммита, тега и push, но в одноразовой копии
# проекта: ее «GitHub» — пустой репозиторий во временной папке. Настоящий репозиторий прогон
# не меняет, это проверяется последним пунктом. Тесты запускает .github/workflows/tests.yml.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1

passed=0
failed=0
skipped=0

ok()   { echo "✅ $1"; passed=$((passed + 1)); }
bad()  { echo "❌ $1"; [ $# -gt 1 ] && printf '   %s\n' "${@:2}"; failed=$((failed + 1)); }
skip() { echo "⏭  $1"; skipped=$((skipped + 1)); }

STATUS_BEFORE="$(git status --porcelain)"
VER="$(sed -nE 's/^VERSION = "([^"]*)".*/\1/p' backup_app/backend/constants.py | head -n1)"
# Следующая версия: заведомо свободна и больше текущей.
NEXT="$(echo "$VER" | awk -F. '{ printf "%s.%s.%d", $1, $2, $3 + 1 }')"
# Версия меньше текущей (пусто, если текущая 0.0.0).
LOWER="$(echo "$VER" | awk -F. '
  $3 > 0 { printf "%s.%s.%d", $1, $2, $3 - 1; exit }
  $2 > 0 { printf "%s.%d.99", $1, $2 - 1; exit }
  $1 > 0 { printf "%d.99.99", $1 - 1; exit }')"
TODAY="$(date +%F)"
WF=".github/workflows/release.yml"

echo "Тесты скриптов выпуска (версия в коде $VER)"
echo

# ── 1. Синтаксис скриптов ─────────────────────────────────────────────────────
errs=""
for s in "$HERE"/*.sh; do
  bash -n "$s" 2>/dev/null || errs="$errs $(basename "$s")"
done
[ -z "$errs" ] && ok "1. Синтаксис всех скриптов" || bad "1. Синтаксис скриптов" "ошибки в:$errs"

# ── 2. check-version.sh ───────────────────────────────────────────────────────
if bash "$HERE/check-version.sh" > /dev/null 2>&1; then
  out="$(bash "$HERE/check-version.sh" 9.9.9 2>&1)"
  if [ $? -ne 0 ] && [ "$(printf '%s\n' "$out" | grep -c '✗')" -eq 3 ]; then
    ok "2. check-version.sh: версия согласована, на 9.9.9 три расхождения"
  else
    bad "2. check-version.sh не нашел трех расхождений на 9.9.9" "$out"
  fi
else
  bad "2. check-version.sh не согласен с текущим состоянием" \
      "запустите scripts/github-release/check-version.sh и посмотрите вывод"
fi

# ── 3. release-notes.sh ───────────────────────────────────────────────────────
notes="$(bash "$HERE/release-notes.sh" "$VER" 2>&1)"
if [ $? -ne 0 ]; then
  bad "3. release-notes.sh завершился с ошибкой" "$notes"
else
  miss=""
  for marker in "## Что нового" "## Скачать" "## Первый запуск" "## Обновление" \
                "BackupApp-$VER-windows-x64.exe" "BackupApp-$VER-macos-arm64.dmg" \
                "BackupApp-$VER-macos-x64.dmg" "BackupApp-$VER-linux-x64.tar.gz" \
                "Выполнить в любом случае" "Все равно открыть" "Автозапуск при входе в систему"; do
    printf '%s\n' "$notes" | grep -F "$marker" > /dev/null || miss="$miss «${marker}»"
  done
  # Незаполненные заготовки: <версия>, TODO, XXX, {{…}}. Кириллица ловится как «не латиница»:
  # диапазон [а-я] в локали C недопустим, и grep молча ничего бы не проверил.
  left="$(printf '%s\n' "$notes" | grep -nE '<[^>a-zA-Z/!][^>]*>|TODO|XXX|\{\{')"
  if [ -n "$miss" ]; then
    bad "3. В описании релиза не хватает:$miss"
  elif [ -n "$left" ]; then
    bad "3. В описании релиза остались заготовки" "$left"
  elif printf '%s' "$notes" | tr -d '\n' | grep "$(printf '\r')" > /dev/null; then
    bad "3. В описании релиза остались символы \\r"
  else
    ok "3. release-notes.sh: описание релиза собрано полностью"
  fi
fi

# ── 4. Workflow ───────────────────────────────────────────────────────────────
wf_problems=""
if [ -f "$WF" ]; then
  # Релиз запускается только тегом и вручную, не обычным push и не pull request.
  grep -q "tags:" "$WF"              || wf_problems="$wf_problems нет триггера по тегам;"
  grep -q "workflow_dispatch:" "$WF" || wf_problems="$wf_problems нет workflow_dispatch;"
  grep -qE "^[[:space:]]+branches:" "$WF" && wf_problems="$wf_problems ЛИШНИЙ триггер по веткам;"
  grep -q "pull_request:" "$WF"      && wf_problems="$wf_problems ЛИШНИЙ триггер pull_request;"
  # В шагах с pipefail «команда | grep -q …» ломается: grep закрывает канал на первом
  # совпадении, источник получает SIGPIPE, и шаг падает именно потому, что совпадение нашлось.
  # Строки-комментарии пропускаются: в них конструкция упоминается для объяснения.
  if grep -nE '^[[:space:]]*[^#[:space:]].*\|[[:space:]]*grep[[:space:]]+-[A-Za-z]*q' "$WF" > /dev/null; then
    wf_problems="$wf_problems «| grep -q» ломается о pipefail, уберите -q;"
  fi
  # Имена файлов в описании релиза и в workflow должны совпадать. Одинарные кавычки
  # намеренно: в workflow ищется сам текст $VER и $TARGET.
  # shellcheck disable=SC2016
  for name in 'BackupApp-$VER-windows-x64.exe' 'BackupApp-$VER-linux-x64.tar.gz' \
              'BackupApp-$VER-$TARGET.dmg' 'target: macos-arm64' 'target: macos-x64'; do
    grep -F "$name" "$WF" > /dev/null || wf_problems="$wf_problems нет «${name}»;"
  done
fi

if [ ! -f "$WF" ]; then
  bad "4. Нет файла $WF"
elif [ -n "$wf_problems" ]; then
  bad "4. Проблемы в $WF" "$wf_problems"
elif command -v actionlint > /dev/null 2>&1; then
  out="$(actionlint "$WF" 2>&1)"
  [ $? -eq 0 ] && ok "4. Workflow: триггеры, имена файлов и actionlint без замечаний" \
               || bad "4. actionlint нашел проблемы" "$out"
else
  ok "4. Workflow: триггеры и имена файлов в порядке"
  skip "4а. actionlint не установлен, полная проверка workflow пропущена"
fi

# ── Песочница для release.sh ──────────────────────────────────────────────────
SANDBOX="$(mktemp -d)"
trap 'rm -rf "$SANDBOX"' EXIT
ORIGIN="$SANDBOX/origin.git"
WORK="$SANDBOX/work"
HIST="$WORK/scripts/github-release/release-history.md"

# Свежая копия проекта: только файлы, которые читает и меняет release.sh, плюс «GitHub».
new_sandbox() {
  rm -rf "$ORIGIN" "$WORK"
  git init --quiet --bare -b master "$ORIGIN"
  git init --quiet -b master "$WORK"
  (
    cd "$WORK" || exit 1
    git config user.name "release-test"
    git config user.email "release-test@example.invalid"
    git config core.autocrlf false   # без предупреждений о переводах строк на Windows
    mkdir -p backup_app/backend scripts/github-release
    cp "$ROOT/backup_app/backend/constants.py" backup_app/backend/
    cp "$ROOT/README.md" .
    cp "$HERE"/*.sh "$HERE/release-history.md" scripts/github-release/
    git add -A 2>/dev/null
    git commit --quiet -m "Начальное состояние"
    git remote add origin "$ORIGIN"
    git push --quiet origin master 2>/dev/null
  )
}

# release.sh в песочнице. Первый аргумент — ответ на вопрос «Выпустить?».
release() {
  local answer="$1"
  shift
  (cd "$WORK" && bash scripts/github-release/release.sh "$@" <<< "$answer" 2>&1)
}

# Добавить запись в «## [Не выпущено]» и отправить ее в «GitHub».
add_unreleased() {
  awk -v text="$1" '{ print } index($0, "## [Не выпущено]") == 1 { print ""; print text }' "$HIST" > "$HIST.new" \
    && mv "$HIST.new" "$HIST"
  (cd "$WORK" && git commit --quiet -am "Описание версии" && git push --quiet origin master 2>/dev/null)
}

new_sandbox

# ── 5. release.sh отвергает некорректные версии ───────────────────────────────
reject() { ! release n "$1" --dry-run --skip-tests > /dev/null; }
bad5=""
reject "1.0"         || bad5="$bad5 «1.0»"
reject "9.0.1-rc.1"  || bad5="$bad5 «9.0.1-rc.1»"
reject "1.2.3.4"     || bad5="$bad5 «1.2.3.4»"
if [ -n "$LOWER" ]; then
  reject "$LOWER"    || bad5="$bad5 «${LOWER}» (меньше текущей)"
fi
[ -z "$bad5" ] && ok "5. release.sh отвергает некорректные версии" || bad "5. release.sh пропустил:$bad5"

# ── 6. Без описания версии выпуск не начинается ───────────────────────────────
out="$(release y "$NEXT" --skip-tests)"
if [ $? -ne 0 ] && printf '%s\n' "$out" | grep "Не выпущено" > /dev/null \
   && [ -z "$(git -C "$WORK" tag)" ]; then
  ok "6. release.sh $NEXT без описания: остановлен, тег не поставлен"
else
  bad "6. release.sh $NEXT без описания не остановился" "$out"
fi

# ── 7. Отказ на вопрос «Выпустить?» ничего не меняет ─────────────────────────
add_unreleased "- Проверочная запись release-test."
out="$(release n "$NEXT" --skip-tests)"
if [ $? -eq 0 ] && printf '%s\n' "$out" | grep "Отменено" > /dev/null \
   && [ -z "$(git -C "$WORK" status --porcelain)" ] && [ -z "$(git -C "$WORK" tag)" ]; then
  ok "7. Ответ «n»: выпуск отменен, файлы и теги не тронуты"
else
  bad "7. Ответ «n» что-то изменил" "$out" "$(git -C "$WORK" status --short)"
fi

# ── 8. --dry-run доходит до плана и ничего не меняет ─────────────────────────
out="$(release y "$NEXT" --dry-run --skip-tests)"
if [ $? -eq 0 ] && printf '%s\n' "$out" | grep "проверки пройдены" > /dev/null \
   && [ -z "$(git -C "$WORK" status --porcelain)" ]; then
  ok "8. --dry-run $NEXT: план напечатан, файлы не тронуты"
else
  bad "8. --dry-run $NEXT" "$out"
fi

# ── 9. Настоящий выпуск: версия, история, коммит, тег, push ───────────────────
out="$(release y "$NEXT" --skip-tests)"
code=$?
heads="$(grep '^## \[' "$HIST" | tr -d '\r' | head -n 2 | tr '\n' '|')"
section="$(awk -v head="## [$NEXT]" '{ sub(/\r$/, "") } index($0, head) == 1 { f = 1; next } f && /^## \[/ { exit } f' "$HIST")"
prob9=""
[ $code -eq 0 ] || prob9="$prob9 код возврата $code;"
grep -F "VERSION = \"$NEXT\"" "$WORK/backup_app/backend/constants.py" > /dev/null || prob9="$prob9 VERSION не $NEXT;"
grep -F "badge/version-$NEXT-blue" "$WORK/README.md" > /dev/null || prob9="$prob9 бейдж не $NEXT;"
[ "$heads" = "## [Не выпущено]|## [$NEXT] — $TODAY|" ] || prob9="$prob9 заголовки истории: $heads;"
printf '%s\n' "$section" | grep -F "Проверочная запись release-test." > /dev/null || prob9="$prob9 запись не попала в секцию $NEXT;"
[ "$(git -C "$WORK" log -1 --format=%s)" = "Выпуск версии $NEXT" ] || prob9="$prob9 нет коммита «Выпуск версии ${NEXT}»;"
[ "$(git -C "$WORK" cat-file -t "v$NEXT" 2>/dev/null)" = "tag" ] || prob9="$prob9 нет аннотированного тега v$NEXT;"
[ "$(git -C "$ORIGIN" rev-parse "v$NEXT^{commit}" 2>/dev/null)" = "$(git -C "$WORK" rev-parse HEAD)" ] \
  || prob9="$prob9 тег не отправлен в origin;"
[ "$(git -C "$ORIGIN" rev-parse master)" = "$(git -C "$WORK" rev-parse HEAD)" ] || prob9="$prob9 master не отправлена;"
(cd "$WORK" && bash scripts/github-release/check-version.sh "$NEXT" > /dev/null 2>&1) \
  || prob9="$prob9 check-version.sh $NEXT не согласен;"
[ -z "$(git -C "$WORK" status --porcelain)" ] || prob9="$prob9 остались незакоммиченные правки;"
[ -z "$prob9" ] && ok "9. Выпуск $NEXT: версия, история, коммит, тег и push на месте" \
                || bad "9. Выпуск $NEXT" "$prob9" "$out"

# ── 10. Тег уже занят ─────────────────────────────────────────────────────────
out="$(release y "$NEXT" --skip-tests)"
if [ $? -ne 0 ] && printf '%s\n' "$out" | grep "уже существует" > /dev/null; then
  ok "10. Повторный выпуск $NEXT: отказ, тег занят"
else
  bad "10. Повторный выпуск $NEXT не остановлен" "$out"
fi

# ── 11. Первый выпуск текущей версии: секция уже заведена ─────────────────────
# Так выходит версия, записанная в коде до появления скриптов выпуска: VERSION не меняется,
# в заголовок секции ставится дата.
new_sandbox
out="$(release y "$VER" --skip-tests)"
code=$?
head_ver="$(grep -F "## [$VER]" "$HIST" | tr -d '\r' | head -n 1)"
if [ $code -eq 0 ] && [ "$head_ver" = "## [$VER] — $TODAY" ] \
   && [ "$(git -C "$ORIGIN" rev-parse "v$VER^{commit}" 2>/dev/null)" = "$(git -C "$WORK" rev-parse HEAD)" ]; then
  ok "11. Выпуск текущей версии $VER: дата в истории, тег отправлен"
else
  bad "11. Выпуск текущей версии $VER" "заголовок: $head_ver" "$out"
fi

# ── 12. Предусловия: неотправленный коммит, грязное дерево, чужая ветка ────────
new_sandbox
add_unreleased "- Еще одна проверочная запись."
prob12=""
(cd "$WORK" && echo "# правка" >> README.md && git commit --quiet -am "Не отправлено")
out="$(release y "$NEXT" --dry-run --skip-tests)"
printf '%s\n' "$out" | grep "неотправленные коммиты" > /dev/null || prob12="$prob12 неотправленный коммит не замечен;"
(cd "$WORK" && git push --quiet origin master 2>/dev/null && echo "# правка" >> README.md)
out="$(release y "$NEXT" --dry-run --skip-tests)"
printf '%s\n' "$out" | grep "рабочее дерево не чистое" > /dev/null || prob12="$prob12 грязное дерево не замечено;"
(cd "$WORK" && git checkout --quiet -- README.md && git checkout --quiet -b feature)
out="$(release y "$NEXT" --dry-run --skip-tests)"
printf '%s\n' "$out" | grep "релизы выпускаются из master" > /dev/null || prob12="$prob12 чужая ветка не замечена;"
[ -z "$(git -C "$WORK" tag)" ] || prob12="$prob12 появился тег;"
[ -z "$prob12" ] && ok "12. Неотправленный коммит, грязное дерево и чужая ветка останавливают выпуск" \
                 || bad "12. Предусловия" "$prob12"

# ── 13. Настоящий репозиторий не тронут ───────────────────────────────────────
[ "$(git status --porcelain)" = "$STATUS_BEFORE" ] \
  && ok "13. Прогон тестов не изменил рабочее дерево проекта" \
  || bad "13. Прогон тестов изменил рабочее дерево проекта" "$(git status --short)"

# ── Итог ──────────────────────────────────────────────────────────────────────
echo
echo "Пройдено: $passed, пропущено: $skipped, провалено: $failed"
exit $(( failed > 0 ))
