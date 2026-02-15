# Vitaliy COO Agent (Telegram + Notion + OpenAI)

Персональный COO-агент с режимом **FOCUS LOCK 30 DAYS**:
- общение через Telegram
- задачи и проекты в Notion
- reasoning/ответы через OpenAI API
- готов к деплою на Railway

## 1) Что умеет MVP

- Создаёт рабочее пространство в Notion (`/setup`):
  - `COO Workspace` (страница)
  - `COO Projects` (база)
  - `COO Tasks` (база)
- Добавляет задачи: `/newtask ...` или сообщение `Задача: ...`
- Добавляет проекты: `/newproject ...`
- Показывает текущий срез: `/focus`
- На любое сообщение отвечает в заданном формате COO-промпта

## 2) Подготовка Notion

1. Создай Notion Integration и получи `NOTION_TOKEN`.
2. Создай (или выбери) страницу-контейнер в Notion.
3. Подели эту страницу с Integration (Share → Invite).
4. Скопируй ID страницы в `NOTION_PARENT_PAGE_ID`.

## 3) Локальный запуск

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m app.main
```

## 4) Переменные окружения

См. [.env.example](.env.example).

Обязательные:
- `TELEGRAM_BOT_TOKEN`
- `OPENAI_API_KEY`
- `NOTION_TOKEN`
- `NOTION_PARENT_PAGE_ID`

Рекомендуется:
- `TELEGRAM_ALLOWED_USER_ID` (чтобы только ты имел доступ)
- `NOTION_ACCESS_PHRASE` (секретная фраза; перед работой с Notion в Telegram используй `/unlock <фраза>`)

## 5) Команды в Telegram

- `/start`
- `/help`
- `/unlock моя-секретная-фраза`
- `/setup`
- `/focus`
- `/newtask Подготовить оффер B2B`
- `/newproject Воронка Q2`

## 6) GitHub

```bash
git init
git add .
git commit -m "init: coo telegram notion agent"
git branch -M main
git remote add origin <YOUR_GITHUB_REPO_URL>
git push -u origin main
```

## 7) Railway deploy

1. New Project → Deploy from GitHub repo.
2. Добавь Variables из `.env`.
3. В проект добавлен `Dockerfile`, Railway будет собирать контейнер без `mise`/python-build-standalone.
4. Start command внутри контейнера: `python -m app.main`.
4. После деплоя открой Telegram и отправь `/setup`.

Если ранее был DNS-fail при установке Python через `mise`, просто запусти redeploy — теперь используется Docker-сборка.

---

Если хочешь, следующим шагом добавлю:
- weekly review авто-ритуал,
- отчёт KPI по расписанию,
- голосовые сообщения,
- режим webhook вместо polling.
