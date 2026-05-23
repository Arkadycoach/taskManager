"""
Task Manager Bot — FastAPI + Telegram + Google Sheets (Apps Script совместимый)
Структура листа "📋 Задачи":
  Строки 1-3 = баннер/подсказка/заголовки (Apps Script)
  Строки 4+   = данные
  Колонки A-M = видимые, N-R = скрытые (Python метаданные)
"""

import asyncio, json, logging, os, uuid
from datetime import datetime, timedelta, date
from typing import Optional

import gspread
import httpx
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from google.oauth2.service_account import Credentials
from pydantic import BaseModel
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ══════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════
BOT_TOKEN        = os.getenv("BOT_TOKEN",        "YOUR_BOT_TOKEN")
WEBAPP_URL       = os.getenv("WEBAPP_URL",        "https://your-frontend-url.com")
SHEET_ID         = os.getenv("SHEET_ID",          "YOUR_GOOGLE_SHEET_ID")
GOOGLE_CREDS_JSON= os.getenv("GOOGLE_CREDS_JSON", "")
APPS_SCRIPT_URL  = os.getenv("APPS_SCRIPT_URL",   "")  # URL из Deploy → Web app

SHEET_NAME     = "📋 Задачи"   # Совпадает с Apps Script
LOG_SHEET_NAME = "ChangeLog"
DATA_START     = 3              # Данные начинаются с индекса 3 (строка 4 в Sheets)

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# ── Индексы колонок (0-based в Python, 1-based в gspread) ────
C_NUM      = 0   # A — #
C_TITLE    = 1   # B — Название задачи
C_PROJECT  = 2   # C — Проект
C_START    = 3   # D — Дата начала
C_DEADLINE = 4   # E — Дедлайн
C_STATUS   = 5   # F — Статус
C_PRIORITY = 6   # G — Приоритет
C_ASSIGNEE = 7   # H — Исполнитель
C_PROGRESS = 8   # I — % Прогресс
C_EST_HRS  = 9   # J — Оценка (ч)
C_ACT_HRS  = 10  # K — Факт (ч)
C_COMMENT  = 11  # L — Комментарий
C_CAL_ID   = 12  # M — ID Календаря
C_TASK_ID  = 13  # N — Task ID (Python UUID)
C_USER_ID  = 14  # O — Telegram UserID
C_USERNAME = 15  # P — Имя пользователя
C_CREATED  = 16  # Q — Создано
C_UPDATED  = 17  # R — Обновлено

TOTAL_COLS = 18

COLUMNS = [
    "#", "Название задачи", "Проект", "Дата начала", "Дедлайн",
    "Статус", "Приоритет", "Исполнитель", "% Прогресс",
    "Оценка (ч)", "Факт (ч)", "Комментарий", "ID Календаря",
    "Task ID", "Telegram UserID", "Имя пользователя", "Создано", "Обновлено"
]

# ── Маппинги статус/приоритет ────────────────────────────────
STATUS_TO_RU = {
    "todo":      "Не начато",
    "doing":     "В работе",
    "review":    "На ревью",
    "done":      "Готово",
    "paused":    "Пауза",
    "cancelled": "Отменено",
}
STATUS_FROM_RU = {
    "Не начато": "todo",
    "Новая":     "todo",   # backward compat
    "В работе":  "doing",
    "На ревью":  "review",
    "Готово":    "done",
    "Пауза":     "paused",
    "Отменено":  "cancelled",
}
PRIORITY_TO_RU = {
    "high":   "🔴 Высокий",
    "medium": "🟡 Средний",
    "low":    "🟢 Низкий",
}
PRIORITY_FROM_RU = {
    "🔴 Высокий": "high",
    "🟡 Средний": "medium",
    "🟢 Низкий":  "low",
    # backward compat
    "Высокий": "high", "Средний": "medium", "Низкий": "low",
}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# GOOGLE SHEETS CLIENT
# ══════════════════════════════════════════════════════════════
def get_sheets_client():
    creds_dict = (json.loads(GOOGLE_CREDS_JSON) if GOOGLE_CREDS_JSON
                  else json.load(open("service_account.json")))
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)


def get_sheet(name=SHEET_NAME):
    client      = get_sheets_client()
    spreadsheet = client.open_by_key(SHEET_ID)
    try:
        return spreadsheet.worksheet(name)
    except gspread.WorksheetNotFound:
        # Создаём совместимый лист (Apps Script его потом красиво оформит)
        sheet = spreadsheet.add_worksheet(title=name, rows=1000, cols=TOTAL_COLS)
        # 3 строки-заголовка для совместимости с Apps Script
        sheet.append_row(["📋 МЕНЕДЖЕР ЗАДАЧ"] + [""] * (TOTAL_COLS - 1))
        sheet.append_row(["Данные из Telegram-бота"] + [""] * (TOTAL_COLS - 1))
        sheet.append_row(COLUMNS)
        return sheet


def get_log_sheet():
    client      = get_sheets_client()
    spreadsheet = client.open_by_key(SHEET_ID)
    try:
        return spreadsheet.worksheet(LOG_SHEET_NAME)
    except gspread.WorksheetNotFound:
        s = spreadsheet.add_worksheet(title=LOG_SHEET_NAME, rows=1000, cols=7)
        s.append_row(["Время","UserID","Пользователь","Действие","ID задачи","Название","Изменения"])
        return s


# ══════════════════════════════════════════════════════════════
# DATA MODELS
# ══════════════════════════════════════════════════════════════
class TaskCreate(BaseModel):
    title:       str
    description: str = ""
    project:     str = ""
    status:      str = "todo"
    priority:    str = "medium"
    deadline:    str = ""
    start_date:  str = ""
    assignee:    str = ""
    progress:    float = 0.0
    user_id:     str = ""
    user_name:   str = ""


class TaskUpdate(BaseModel):
    title:       Optional[str]   = None
    description: Optional[str]   = None
    project:     Optional[str]   = None
    status:      Optional[str]   = None
    priority:    Optional[str]   = None
    deadline:    Optional[str]   = None
    start_date:  Optional[str]   = None
    assignee:    Optional[str]   = None
    progress:    Optional[float] = None
    user_id:     str = ""
    user_name:   str = ""


def row_to_task(row: list) -> dict:
    """Конвертирует строку таблицы → dict задачи (поддержка рус/англ значений)"""
    def get(i): return row[i] if i < len(row) else ""

    raw_status   = str(get(C_STATUS))
    raw_priority = str(get(C_PRIORITY))

    status   = STATUS_FROM_RU.get(raw_status,   raw_status   if raw_status   in STATUS_TO_RU   else "todo")
    priority = PRIORITY_FROM_RU.get(raw_priority, raw_priority if raw_priority in PRIORITY_TO_RU else "medium")

    # Дедлайн может быть datetime объектом (при чтении через gspread)
    deadline_val = get(C_DEADLINE)
    if hasattr(deadline_val, "strftime"):
        deadline_val = deadline_val.strftime("%Y-%m-%d")

    start_val = get(C_START)
    if hasattr(start_val, "strftime"):
        start_val = start_val.strftime("%Y-%m-%d")

    return {
        "id":          str(get(C_TASK_ID)),
        "title":       str(get(C_TITLE)),
        "description": str(get(C_COMMENT)),
        "project":     str(get(C_PROJECT)),
        "status":      status,
        "priority":    priority,
        "deadline":    str(deadline_val),
        "start_date":  str(start_val),
        "assignee":    str(get(C_ASSIGNEE)),
        "progress":    get(C_PROGRESS) or 0,
        "user_id":     str(get(C_USER_ID)),
        "user_name":   str(get(C_USERNAME)),
        "created_at":  str(get(C_CREATED)),
        "updated_at":  str(get(C_UPDATED)),
    }


def task_to_row(task_id, task: TaskCreate, user_id: str, row_num: int, now: str) -> list:
    """Создаёт строку для вставки в Sheets"""
    return [
        row_num,                                              # A — #
        task.title,                                           # B — Название
        task.project,                                         # C — Проект
        task.start_date or "",                                # D — Дата начала
        task.deadline,                                        # E — Дедлайн
        STATUS_TO_RU.get(task.status,   "Не начато"),        # F — Статус
        PRIORITY_TO_RU.get(task.priority, "🟡 Средний"),      # G — Приоритет
        task.assignee,                                        # H — Исполнитель
        task.progress,                                        # I — Прогресс
        0,                                                    # J — Оценка
        0,                                                    # K — Факт
        task.description,                                     # L — Комментарий
        "",                                                   # M — ID Календаря
        task_id,                                              # N — Task ID
        user_id,                                              # O — UserID
        task.user_name,                                       # P — Имя
        now,                                                  # Q — Создано
        now,                                                  # R — Обновлено
    ]


# ══════════════════════════════════════════════════════════════
# APPS SCRIPT УВЕДОМЛЕНИЯ
# ══════════════════════════════════════════════════════════════
async def notify_apps_script(action: str, task_data: dict, changes: list = None):
    """Вызывает Apps Script Web App для отправки email и Calendar синхронизации"""
    if not APPS_SCRIPT_URL:
        return
    payload = {"action": action, "task": task_data}
    if changes:
        payload["changes"] = changes
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(APPS_SCRIPT_URL, json=payload)
    except Exception as e:
        logger.warning(f"Apps Script notify error: {e}")


# ══════════════════════════════════════════════════════════════
# FASTAPI APP
# ══════════════════════════════════════════════════════════════
app = FastAPI(title="Task Manager API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

bot = Bot(token=BOT_TOKEN)
user_chat_ids: dict[str, int] = {}


@app.get("/tasks")
async def get_tasks(user_id: str = ""):
    try:
        sheet    = get_sheet()
        all_rows = sheet.get_all_values()
        if len(all_rows) <= DATA_START:
            return {"tasks": []}

        tasks = []
        for row in all_rows[DATA_START:]:          # Пропускаем 3 строки-заголовка
            if len(row) < 2 or not row[C_TITLE]:   # Пустая строка
                continue
            task = row_to_task(row)
            tasks.append(task)

        return {"tasks": tasks}
    except Exception as e:
        logger.error(f"get_tasks error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/tasks")
async def create_task(task: TaskCreate, x_user_id: str = Header(default="")):
    try:
        sheet    = get_sheet()
        all_rows = sheet.get_all_values()
        task_id  = str(uuid.uuid4())[:8].upper()
        now      = datetime.now().isoformat(timespec="seconds")
        user_id  = task.user_id or x_user_id

        # Авто-нумерация
        data_rows = [r for r in all_rows[DATA_START:] if r and len(r) > 1 and r[C_TITLE]]
        row_number = len(data_rows) + 1

        row = task_to_row(task_id, task, user_id, row_number, now)
        sheet.append_row(row)

        new_task = {
            "id": task_id, "title": task.title, "description": task.description,
            "project": task.project, "status": task.status, "priority": task.priority,
            "deadline": task.deadline, "start_date": task.start_date,
            "assignee": task.assignee, "progress": task.progress,
            "user_id": user_id, "user_name": task.user_name,
            "created_at": now, "updated_at": now,
        }

        _log_change(user_id, task.user_name, "СОЗДАНИЕ", task_id, task.title,
                    f"Создана задача: {task.title}")

        # Уведомляем Apps Script → email + Calendar
        asyncio.create_task(notify_apps_script("task_created", {
            **new_task,
            "status":   STATUS_TO_RU.get(task.status, task.status),
            "priority": PRIORITY_TO_RU.get(task.priority, task.priority),
        }))

        return {"task": new_task}
    except Exception as e:
        logger.error(f"create_task error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/tasks/{task_id}")
async def update_task(task_id: str, update: TaskUpdate, x_user_id: str = Header(default="")):
    try:
        sheet    = get_sheet()
        all_rows = sheet.get_all_values()

        row_idx  = None
        old_task = None
        for i, row in enumerate(all_rows[DATA_START:], start=DATA_START + 1):
            if len(row) > C_TASK_ID and row[C_TASK_ID] == task_id:
                row_idx  = i
                old_task = row_to_task(row)
                break

        if row_idx is None:
            raise HTTPException(status_code=404, detail="Task not found")

        changes = []
        sl = {"todo":"Не начато","doing":"В работе","review":"На ревью",
              "done":"Готово","paused":"Пауза","cancelled":"Отменено"}
        pl = {"high":"🔴 Высокий","medium":"🟡 Средний","low":"🟢 Низкий"}

        def upd(col_1based, value, label=None, old_val=None):
            sheet.update_cell(row_idx, col_1based, value)
            if label and old_val is not None and old_val != value:
                changes.append(f"{label}: {old_val} → {value}")

        if update.title       is not None: upd(C_TITLE    +1, update.title,       "название",    old_task["title"])
        if update.description is not None: upd(C_COMMENT  +1, update.description)
        if update.project     is not None: upd(C_PROJECT  +1, update.project,     "проект",      old_task["project"])
        if update.start_date  is not None: upd(C_START    +1, update.start_date)
        if update.deadline    is not None: upd(C_DEADLINE +1, update.deadline,    "дедлайн",     old_task["deadline"])
        if update.assignee    is not None: upd(C_ASSIGNEE +1, update.assignee,    "исполнитель", old_task["assignee"])
        if update.progress    is not None: upd(C_PROGRESS +1, update.progress)

        if update.status is not None:
            ru = STATUS_TO_RU.get(update.status, update.status)
            upd(C_STATUS+1, ru)
            if old_task["status"] != update.status:
                changes.append(f"статус: {sl.get(old_task['status'])} → {sl.get(update.status)}")

        if update.priority is not None:
            ru = PRIORITY_TO_RU.get(update.priority, update.priority)
            upd(C_PRIORITY+1, ru)
            if old_task["priority"] != update.priority:
                changes.append(f"приоритет: {pl.get(update.priority)}")

        now = datetime.now().isoformat(timespec="seconds")
        sheet.update_cell(row_idx, C_UPDATED + 1, now)

        user_id = update.user_id or x_user_id
        if changes:
            _log_change(user_id, update.user_name, "ОБНОВЛЕНИЕ", task_id,
                        update.title or old_task["title"], "; ".join(changes))

        # Уведомляем Apps Script
        updated_task = {**old_task}
        for k, v in update.dict(exclude_none=True).items():
            updated_task[k] = v
        asyncio.create_task(notify_apps_script("task_updated", {
            **updated_task,
            "status":   STATUS_TO_RU.get(updated_task.get("status",""), ""),
            "priority": PRIORITY_TO_RU.get(updated_task.get("priority",""), ""),
        }, changes))

        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"update_task error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/tasks/{task_id}")
async def delete_task(task_id: str, x_user_id: str = Header(default="")):
    try:
        sheet    = get_sheet()
        all_rows = sheet.get_all_values()
        for i, row in enumerate(all_rows[DATA_START:], start=DATA_START + 1):
            if len(row) > C_TASK_ID and row[C_TASK_ID] == task_id:
                task_title = row[C_TITLE] if len(row) > C_TITLE else task_id
                sheet.delete_rows(i)
                _log_change(x_user_id, "", "УДАЛЕНИЕ", task_id, task_title, "Задача удалена")
                asyncio.create_task(notify_apps_script("task_deleted", {"id": task_id}))
                return {"success": True}
        raise HTTPException(status_code=404, detail="Task not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"delete_task error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/register")
async def register_user(data: dict):
    uid  = str(data.get("user_id", ""))
    chat = data.get("chat_id")
    if uid and chat:
        user_chat_ids[uid] = int(chat)
    return {"ok": True}


# ══════════════════════════════════════════════════════════════
# SHEETS → APP SYNC (polling каждые 60 сек)
# Именно это позволяет видеть изменения из Google Sheets в приложении
# ══════════════════════════════════════════════════════════════
_last_sheet_state: dict[str, dict] = {}

async def check_sheet_changes():
    global _last_sheet_state
    while True:
        await asyncio.sleep(60)
        try:
            sheet    = get_sheet()
            all_rows = sheet.get_all_values()

            current = {}
            for row in all_rows[DATA_START:]:
                if len(row) > C_TASK_ID and row[C_TASK_ID]:
                    task = row_to_task(row)
                    current[task["id"]] = task

            if _last_sheet_state:
                sl = {"todo":"Новая","doing":"В работе","review":"На ревью",
                      "done":"Готово","paused":"Пауза","cancelled":"Отменено"}
                pl = {"high":"🔴 Высокий","medium":"🟡 Средний","low":"🟢 Низкий"}

                for tid, task in current.items():
                    if tid in _last_sheet_state:
                        old      = _last_sheet_state[tid]
                        changes  = []
                        if old["title"]    != task["title"]:    changes.append(f"📝 Название: *{task['title']}*")
                        if old["status"]   != task["status"]:   changes.append(f"🔄 Статус: {sl.get(old['status'])} → *{sl.get(task['status'])}*")
                        if old["priority"] != task["priority"]: changes.append(f"⚡ Приоритет: {pl.get(task['priority'])}")
                        if old["deadline"] != task["deadline"]: changes.append(f"📅 Дедлайн: *{task['deadline'] or 'убран'}*")
                        if old["assignee"] != task["assignee"]: changes.append(f"👤 Исполнитель: *{task['assignee'] or '—'}*")
                        if old["project"]  != task["project"]:  changes.append(f"📁 Проект: *{task['project'] or '—'}*")

                        if changes:
                            chat_id = user_chat_ids.get(task["user_id"])
                            if chat_id:
                                msg = f"📊 *Изменение в Google Sheets*\n\nЗадача: *{task['title']}*\n\n" + "\n".join(changes)
                                await bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
                    else:
                        chat_id = user_chat_ids.get(task["user_id"])
                        if chat_id:
                            msg = f"✅ *Новая задача из Google Sheets*\n\n*{task['title']}*"
                            if task["description"]: msg += f"\n_{task['description']}_"
                            await bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")

                for tid in _last_sheet_state:
                    if tid not in current:
                        old     = _last_sheet_state[tid]
                        chat_id = user_chat_ids.get(old["user_id"])
                        if chat_id:
                            await bot.send_message(chat_id=chat_id,
                                text=f"🗑 *Задача удалена из Sheets*\n\n~~{old['title']}~~", parse_mode="Markdown")

            _last_sheet_state = current
        except Exception as e:
            logger.error(f"check_sheet_changes error: {e}")


# ══════════════════════════════════════════════════════════════
# DAILY REMINDERS
# ══════════════════════════════════════════════════════════════
async def send_daily_reminders():
    while True:
        now       = datetime.now()
        next_9am  = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if now >= next_9am: next_9am += timedelta(days=1)
        await asyncio.sleep((next_9am - now).total_seconds())

        try:
            sheet    = get_sheet()
            all_rows = sheet.get_all_values()
            today    = date.today()
            user_tasks: dict[str, dict] = {}

            for row in all_rows[DATA_START:]:
                if not row or not row[C_TITLE]: continue
                task = row_to_task(row)
                if task["status"] == "done": continue
                uid = task["user_id"]
                if uid not in user_tasks:
                    user_tasks[uid] = {"overdue":[], "today":[], "upcoming":[]}
                if task["deadline"]:
                    try:
                        dl = date.fromisoformat(task["deadline"])
                        if dl < today:                        user_tasks[uid]["overdue"].append(task)
                        elif dl == today:                     user_tasks[uid]["today"].append(task)
                        elif dl <= today + timedelta(days=3): user_tasks[uid]["upcoming"].append(task)
                    except ValueError: pass
                elif task["status"] == "doing":
                    user_tasks[uid]["upcoming"].append(task)

            for uid, buckets in user_tasks.items():
                chat_id = user_chat_ids.get(uid)
                if not chat_id: continue
                if not buckets["overdue"] and not buckets["today"] and not buckets["upcoming"]: continue

                lines = [f"☀️ *Доброе утро! Сводка на {today.strftime('%d.%m.%Y')}*\n"]
                if buckets["overdue"]:
                    lines.append(f"🔴 *Просрочено ({len(buckets['overdue'])}):*")
                    for t in buckets["overdue"][:5]:
                        lines.append(f"  • {t['title']} _{t['deadline']}_")
                if buckets["today"]:
                    lines.append(f"\n🟡 *Дедлайн сегодня ({len(buckets['today'])}):*")
                    for t in buckets["today"]: lines.append(f"  • {t['title']}")
                if buckets["upcoming"]:
                    lines.append(f"\n🟢 *Ближайшие ({len(buckets['upcoming'])}):*")
                    for t in buckets["upcoming"][:3]:
                        dl = f" _{t['deadline']}_" if t["deadline"] else ""
                        lines.append(f"  • {t['title']}{dl}")

                await bot.send_message(
                    chat_id=chat_id, text="\n".join(lines), parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("📋 Открыть задачи", url=WEBAPP_URL)
                    ]])
                )
        except Exception as e:
            logger.error(f"send_daily_reminders error: {e}")


# ══════════════════════════════════════════════════════════════
# TELEGRAM BOT HANDLERS
# ══════════════════════════════════════════════════════════════
async def cmd_start(update, context: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    chat_id = update.effective_chat.id
    user_chat_ids[str(user.id)] = chat_id
    await update.message.reply_text(
        f"👋 Привет, *{user.first_name}*\\!\n\n"
        "Я помогу управлять твоими задачами\\.\n\n"
        "📊 Синхронизация с Google Sheets\n"
        "📅 Синхронизация с Google Calendar\n"
        "📧 Email уведомления при назначении\n"
        "🔔 Ежедневные напоминания в 9:00",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📋 Открыть Task Manager", web_app={"url": WEBAPP_URL})
        ]])
    )


async def cmd_tasks(update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_chat_ids[user_id] = update.effective_chat.id
    try:
        sheet    = get_sheet()
        all_rows = sheet.get_all_values()
        active   = [row_to_task(r) for r in all_rows[DATA_START:]
                    if r and len(r) > C_TITLE and r[C_TITLE] and row_to_task(r)["status"] != "done"]
        if not active:
            await update.message.reply_text("✅ Нет активных задач!")
            return
        si = {"todo":"⚪","doing":"🔵","review":"🟣","done":"✅","paused":"⏸","cancelled":"❌"}
        pi = {"high":"🔴","medium":"🟡","low":"🟢"}
        lines = [f"📋 *Активные задачи ({len(active)}):*\n"]
        for t in active[:10]:
            dl = f" _({t['deadline']})_" if t["deadline"] else ""
            lines.append(f"{si.get(t['status'],'•')}{pi.get(t['priority'],'')} {t['title']}{dl}")
        if len(active) > 10: lines.append(f"\n_... и ещё {len(active)-10}_")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📋 Открыть всё", web_app={"url": WEBAPP_URL})
            ]]))
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def cmd_stats(update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sheet    = get_sheet()
        all_rows = sheet.get_all_values()
        tasks    = [row_to_task(r) for r in all_rows[DATA_START:] if r and len(r)>C_TITLE and r[C_TITLE]]
        total    = len(tasks)
        bs       = {k:0 for k in STATUS_TO_RU}
        overdue  = 0
        today    = date.today()
        for t in tasks:
            bs[t["status"]] = bs.get(t["status"], 0) + 1
            if t["deadline"] and t["status"] != "done":
                try:
                    if date.fromisoformat(t["deadline"]) < today: overdue += 1
                except ValueError: pass
        pct = round(bs.get("done", 0) / total * 100) if total else 0
        await update.message.reply_text(
            f"📊 *Статистика*\n\n"
            f"Всего: *{total}*\n"
            f"├ ⚪ Не начато: {bs.get('todo',0)}\n"
            f"├ 🔵 В работе: {bs.get('doing',0)}\n"
            f"├ 🟣 На ревью: {bs.get('review',0)}\n"
            f"├ ⏸ Пауза: {bs.get('paused',0)}\n"
            f"└ ✅ Готово: {bs.get('done',0)}\n\n"
            f"🔴 Просрочено: {overdue}\n"
            f"📈 Выполнено: {pct}%",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def cmd_help(update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*Команды:*\n\n"
        "/start — открыть Task Manager\n"
        "/tasks — активные задачи\n"
        "/stats — статистика\n"
        "/help — помощь\n\n"
        "_Напоминания каждый день в 9:00_",
        parse_mode="Markdown"
    )


def _log_change(user_id, user_name, action, task_id, task_title, changes):
    try:
        s = get_log_sheet()
        s.append_row([datetime.now().isoformat(timespec="seconds"),
                      user_id, user_name, action, task_id, task_title, changes])
    except Exception as e:
        logger.warning(f"Log error: {e}")


# ══════════════════════════════════════════════════════════════
# STARTUP / SHUTDOWN
# ══════════════════════════════════════════════════════════════
@app.on_event("startup")
async def startup():
    try:
        sheet = get_sheet()
        logger.info(f"✅ Google Sheets connected: {sheet.title}")
    except Exception as e:
        logger.error(f"❌ Google Sheets error: {e}")

    asyncio.create_task(check_sheet_changes())
    asyncio.create_task(send_daily_reminders())
    logger.info("✅ Background tasks started")


@app.on_event("shutdown")
async def shutdown():
    await bot.close()


# ══════════════════════════════════════════════════════════════
# TELEGRAM WEBHOOK
# ══════════════════════════════════════════════════════════════
telegram_app = None

@app.post("/webhook/{token}")
async def telegram_webhook(token: str, request: Request):
    if token != BOT_TOKEN:
        raise HTTPException(status_code=403)
    global telegram_app
    if telegram_app is None:
        telegram_app = Application.builder().token(BOT_TOKEN).build()
        telegram_app.add_handler(CommandHandler("start", cmd_start))
        telegram_app.add_handler(CommandHandler("tasks", cmd_tasks))
        telegram_app.add_handler(CommandHandler("stats", cmd_stats))
        telegram_app.add_handler(CommandHandler("help",  cmd_help))
        await telegram_app.initialize()
    update = Update.de_json(await request.json(), bot)
    await telegram_app.process_update(update)
    return {"ok": True}


@app.get("/health")
async def health():
    return {"status": "ok", "time": datetime.now().isoformat()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
