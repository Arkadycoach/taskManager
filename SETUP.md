# 📋 Task Manager — Инструкция по настройке

## Структура проекта
```
task-manager/
├── frontend/
│   └── index.html          ← Telegram Mini App (UI)
├── backend/
│   ├── main.py             ← FastAPI сервер + Telegram Bot
│   ├── requirements.txt
│   ├── setup_webhook.py    ← Регистрация вебхука
│   └── railway.toml        ← Конфиг для Railway
└── SETUP.md
```

---

## ШАГ 1 — Создай Telegram бота

1. Открой [@BotFather](https://t.me/BotFather) в Telegram
2. Отправь `/newbot`
3. Придумай имя и username (например `@MyTaskManagerBot`)
4. Сохрани **BOT_TOKEN** — он выглядит как `1234567890:AAF...`
5. Включи Mini App:
   - Отправь `/newapp` в BotFather
   - Выбери своего бота
   - Укажи URL фронтенда (настроим позже)

---

## ШАГ 2 — Настрой Google Sheets

### 2.1 Создай таблицу
1. Открой [Google Sheets](https://sheets.google.com)
2. Создай новую таблицу с названием **"Task Manager"**
3. Скопируй **ID таблицы** из URL:
   `https://docs.google.com/spreadsheets/d/`**`ЭТОТ_ID`**`/edit`

### 2.2 Создай Service Account
1. Открой [Google Cloud Console](https://console.cloud.google.com)
2. Создай новый проект (или используй существующий)
3. Включи **Google Sheets API**:
   - APIs & Services → Enable APIs → найди "Google Sheets API" → Enable
4. Создай Service Account:
   - APIs & Services → Credentials → Create Credentials → Service Account
   - Дай любое имя, нажми Create
5. Создай ключ:
   - Кликни на созданный Service Account
   - Вкладка Keys → Add Key → Create new key → JSON
   - Скачается файл `*.json` — это твои credentials

### 2.3 Выдай доступ боту к таблице
1. Открой скачанный JSON файл
2. Найди поле `"client_email"` — скопируй email вида `name@project.iam.gserviceaccount.com`
3. В Google Sheets нажми **Поделиться**
4. Вставь этот email и дай права **Редактор**

---

## ШАГ 3 — Задеплой бэкенд на Railway

### 3.1 Деплой
1. Зарегистрируйся на [Railway.app](https://railway.app)
2. Нажми **New Project** → **Deploy from GitHub repo**
3. Загрузи папку `backend/` в GitHub репозиторий
4. Railway автоматически задетектит Python и задеплоит

### 3.2 Добавь переменные окружения
В Railway → твой проект → Variables добавь:

| Переменная | Значение |
|-----------|---------|
| `BOT_TOKEN` | Токен от BotFather |
| `SHEET_ID` | ID Google Sheets таблицы |
| `GOOGLE_CREDS_JSON` | Содержимое JSON файла (скопируй весь текст) |
| `WEBAPP_URL` | URL фронтенда (из шага 4) |

3. После деплоя скопируй URL сервера, он выглядит как `https://xxx.up.railway.app`

---

## ШАГ 4 — Задеплой фронтенд

### Вариант A: GitHub Pages (бесплатно)
1. Создай репозиторий на GitHub
2. Загрузи `frontend/index.html`
3. Settings → Pages → Source: main branch
4. Получишь URL вида `https://username.github.io/repo/`

### Вариант B: Vercel (бесплатно, рекомендуется)
1. [Vercel.com](https://vercel.com) → New Project
2. Загрузи папку `frontend/`
3. Получишь URL вида `https://xxx.vercel.app`

### Вариант C: Netlify Drop
1. Открой [app.netlify.com/drop](https://app.netlify.com/drop)
2. Перетащи папку `frontend/`
3. Получишь URL сразу

---

## ШАГ 5 — Настрой фронтенд

Открой `frontend/index.html` и замени в самом начале скрипта:

```javascript
const CONFIG = {
  API_URL: 'https://ВАШ_RAILWAY_URL',  // ← Вставь URL из шага 3
  POLL_INTERVAL: 30000,
};
```

Перезалей файл на хостинг.

---

## ШАГ 6 — Зарегистрируй Telegram Webhook

```bash
cd backend/
pip install requests
BOT_TOKEN="твой_токен" SERVER_URL="https://xxx.up.railway.app" python setup_webhook.py
```

---

## ШАГ 7 — Подключи Mini App к боту

1. Открой [@BotFather](https://t.me/BotFather)
2. Отправь `/mybots` → выбери своего бота
3. **Bot Settings** → **Menu Button** → Configure menu button
4. Введи URL фронтенда из шага 4
5. Введи текст кнопки: `📋 Задачи`

---

## Проверка работы

1. Открой бота в Telegram
2. Нажми `/start`
3. Нажми кнопку `📋 Задачи`
4. Добавь задачу через приложение — она должна появиться в Google Sheets
5. Измени статус задачи в Google Sheets — через ~1 минуту придёт уведомление в бот

---

## Структура Google Sheets

Бот автоматически создаст 2 листа:

**Tasks** — основные задачи:
| ID | Title | Description | Status | Priority | Deadline | Assignee | UserID | UserName | CreatedAt | UpdatedAt |
|----|-------|-------------|--------|----------|----------|----------|--------|----------|-----------|-----------|

**ChangeLog** — история изменений:
| Timestamp | UserID | UserName | Action | TaskID | TaskTitle | Changes |
|-----------|--------|----------|--------|--------|-----------|---------|

---

## Уведомления

| Тип | Когда |
|-----|-------|
| 🔔 Изменение из Sheets | Через ~1 минуту после правки в таблице |
| ☀️ Ежедневная сводка | Каждый день в 9:00 |
| 🔴 Просроченные задачи | Включены в утреннюю сводку |
| 🟡 Дедлайн сегодня | Включены в утреннюю сводку |

---

## Поддержка

Если что-то не работает:
- Проверь логи в Railway (раздел Deployments → Logs)
- Убедись что Google Service Account email добавлен в таблицу
- Проверь что все переменные окружения заданы правильно
