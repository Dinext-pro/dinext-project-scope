# Навигация по правилам Dinext

Центральные правила и планы проекта хранятся в OpenSpec Store `dinext-docs`. Обычно репозиторий расположен в `../dinext-docs/`. Если рабочие копии расположены иначе, используйте путь к зарегистрированному Store из `openspec context`. В разреженной рабочей копии прочитайте доступные через Git файлы командой `git -C <store-path> show HEAD:<path>`.

## Порядок работы

1. Из корня приложения выполните `openspec doctor`, `openspec context` и `openspec list`. Подключение Store описано в `process/development-management/openspec-store.md` в `dinext-docs`.
2. В `dinext-docs` прочитайте `agents/ide/runtime-access.md` и реестр `agents/registry/index.yaml`. Откройте руководство `agents/ide/agents/dinext-frappe-developer-guide.md` и относящиеся к задаче материалы по `content_path` из реестра.
3. До изменения кода, метаданных, тестов или документации прочитайте `agents/ide/rules/openspec-mandatory-workflow.md` и `agents/ide/skills/openspec-development-workflow/SKILL.md`. Выберите change в Store, подготовьте proposal, design, specs и tasks. Выполните строгую валидацию и получите инструкции `openspec instructions apply` для этого change.
4. Используйте правила веток и приёмки из `process/development-management/github-development-workflow.md` в `dinext-docs`. Для локальной разработки и проверок Dinext используйте основной WSL-сайт `http://localhost:8000/` с синтетическим проектом.
5. После проверок отметьте подтверждённые задачи в Store. Для изменений интерфейса применяйте обязательные Cypress-тесты по `agents/ide/rules/cypress-ui-tests-mandatory.md`.

Центральные правила имеют приоритет. Локальные материалы `.cursor/` дополняют их. `openspec/config.yaml` приложения хранит указатель `store: dinext-docs`. Спецификации и изменения ведутся в Store.
