"""
Task Manager Bot — полный бэкенд
Стек: FastAPI + python-telegram-bot + gspread (Google Sheets)
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, date
from typing import Optional

import gspread
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from google.oauth2.service_account import Credentials
from pydantic import BaseModel
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                           ContextTypes, MessageHandler, filters)

# ==========================================
# CONFIG
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://your-frontend-url.com")
SHEET_ID = os.getenv("SHEET_ID", "YOUR_GOOGLE_SHEET_ID")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON", "")  # JSON-строка с ключами

# Лист где хранятся задачи
SHEET_NAME = "Tasks"
# Лист куда логируются изменения
LOG_SHEET_NAME = "ChangeLog"

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Колонки таблицы
COLUMNS = ["ID", "Title", "Description", "Status", "Priority",
           "Deadline", "Assignee", "UserID", "UserName", "CreatedAt", "UpdatedAt"]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==========================================
# GOOGLE SHEETS CLIENT
# ==========================================
def get_sheets_client():
    if GOOGLE_CREDS_JSON:
        creds_dict = json.loads(GOOGLE_CREDS_JSON)
    else:
        # Для локальной разработки — читай из файла
        with open("service_account.json") as f:
            creds_dict = json.load(f)
    
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)


def get_sheet(name=SHEET_NAME):
    client = get_sheets_client()
    spreadsheet = client.open_by_key(SHEET_ID)
    try:
        return spreadsheet.worksheet(name)
    except gspread.WorksheetNotFound:
        # Создаём лист если не существует
        sheet = spreadsheet.add_worksheet(title=name, rows=1000, cols=len(COLUMNS))
        if name == SHEET_NAME:
            sheet.append_row(COLUMNS)
        elif name == LOG_SHEET_NAME:
            sheet.append_row(["Timestamp", "UserID", "UserName", "Action", "TaskID", "TaskTitle", "Changes"])
        return sheet


# ==========================================
# DATA MODELS
# ==========================================
class TaskCreate(BaseModel):
    title: str
    description: str = ""
    status: str = "todo"  # todo | doing | done
    priority: str = "medium"  # low | medium | high
    deadline: str = ""
    assignee: str = ""
    user_id: str = ""
    user_name: str = ""


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    deadline: Optional[str] = None
    assignee: Optional[str] = None
    user_id: str = ""
    user_name: str = ""


def row_to_task(row: list) -> dict:
    """Конвертируем строку таблицы в словарь задачи"""
    keys = COLUMNS
    task = {}
    for i, key in enumerate(keys):
        task[key.lower()] = row[i] if i < len(row) else ""
    return {
        "id": task.get("id", ""),
        "title": task.get("title", ""),
        "description": task.get("description", ""),
        "status": task.get("status", "todo"),
        "priority": task.get("priority", "medium"),
        "deadline": task.get("deadline", ""),
        "assignee": task.get("assignee", ""),
        "user_id": task.get("userid", ""),
        "user_name": task.get("username", ""),
        "created_at": task.get("createdat", ""),
        "updated_at": task.get("updatedat", ""),
    }


# ==========================================
# FASTAPI APP
# ==========================================
app = FastAPI(title="Task Manager API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

bot = Bot(token=BOT_TOKEN)

# Кэш chat_id пользователей (user_id -> chat_id)
user_chat_ids: dict[str, int] = {}


@app.get("/tasks")
async def get_tasks(user_id: str = ""):
    """Получить все задачи пользователя"""
    try:
        sheet = get_sheet()
        all_rows = sheet.get_all_values()
        if len(all_rows) <= 1:  # Только заголовки
            return {"tasks": []}
        
        tasks = []
        for row in all_rows[1:]:  # Пропускаем заголовки
            if len(row) < 2 or not row[0]:
                continue
            task = row_to_task(row)
            # Фильтруем по user_id если указан
            if user_id and task["user_id"] and task["user_id"] != user_id:
                continue
            tasks.append(task)
        
        return {"tasks": tasks}
    except Exception as e:
        logger.error(f"get_tasks error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/tasks")
async def create_task(task: TaskCreate, x_user_id: str = Header(default="")):
    """Создать новую задачу"""
    try:
        sheet = get_sheet()
        task_id = str(uuid.uuid4())[:8].upper()
        now = datetime.now().isoformat(timespec="seconds")
        
        user_id = task.user_id or x_user_id
        
        row = [
            task_id,
            task.title,
            task.description,
            task.status,
            task.priority,
            task.deadline,
            task.assignee,
            user_id,
            task.user_name,
            now,
            now,
        ]
        sheet.append_row(row)
        
        new_task = {
            "id": task_id, "title": task.title, "description": task.description,
            "status": task.status, "priority": task.priority, "deadline": task.deadline,
            "assignee": task.assignee, "user_id": user_id, "user_name": task.user_name,
            "created_at": now, "updated_at": now,
        }
        
        # Лог изменения
        _log_change(user_id, task.user_name, "CREATE", task_id, task.title, f"Создана задача: {task.title}")
        
        return {"task": new_task}
    except Exception as e:
        logger.error(f"create_task error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/tasks/{task_id}")
async def update_task(task_id: str, update: TaskUpdate, x_user_id: str = Header(default="")):
    """Обновить задачу"""
    try:
        sheet = get_sheet()
        all_rows = sheet.get_all_values()
        
        row_idx = None
        old_task = None
        for i, row in enumerate(all_rows[1:], start=2):
            if row and row[0] == task_id:
                row_idx = i
                old_task = row_to_task(row)
                break
        
        if row_idx is None:
            raise HTTPException(status_code=404, detail="Task not found")
        
        # Обновляем только переданные поля
        changes = []
        if update.title is not None:
            sheet.update_cell(row_idx, 2, update.title)
            if old_task["title"] != update.title:
                changes.append(f"title: {old_task['title']} → {update.title}")
        if update.description is not None:
            sheet.update_cell(row_idx, 3, update.description)
        if update.status is not None:
            sheet.update_cell(row_idx, 4, update.status)
            if old_task["status"] != update.status:
                status_labels = {"todo": "Новая", "doing": "В работе", "done": "Готово"}
                changes.append(f"статус: {status_labels.get(old_task['status'])} → {status_labels.get(update.status)}")
        if update.priority is not None:
            sheet.update_cell(row_idx, 5, update.priority)
        if update.deadline is not None:
            sheet.update_cell(row_idx, 6, update.deadline)
        if update.assignee is not None:
            sheet.update_cell(row_idx, 7, update.assignee)
        
        now = datetime.now().isoformat(timespec="seconds")
        sheet.update_cell(row_idx, 11, now)  # UpdatedAt
        
        user_id = update.user_id or x_user_id
        if changes:
            _log_change(user_id, update.user_name, "UPDATE", task_id,
                       update.title or old_task["title"], "; ".join(changes))
        
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"update_task error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/tasks/{task_id}")
async def delete_task(task_id: str, x_user_id: str = Header(default="")):
    """Удалить задачу"""
    try:
        sheet = get_sheet()
        all_rows = sheet.get_all_values()
        
        for i, row in enumerate(all_rows[1:], start=2):
            if row and row[0] == task_id:
                task_title = row[1] if len(row) > 1 else task_id
                sheet.delete_rows(i)
                _log_change(x_user_id, "", "DELETE", task_id, task_title, "Задача удалена")
                return {"success": True}
        
        raise HTTPException(status_code=404, detail="Task not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"delete_task error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Регистрация chat_id пользователя
@app.post("/register")
async def register_user(data: dict):
    user_id = str(data.get("user_id", ""))
    chat_id = data.get("chat_id")
    if user_id and chat_id:
        user_chat_ids[user_id] = int(chat_id)
    return {"ok": True}


# ==========================================
# GOOGLE SHEETS WEBHOOK (polling)
# ==========================================
# Хранит последнее известное состояние таблицы
_last_sheet_state: dict[str, dict] = {}

async def check_sheet_changes():
    """
    Периодически проверяет изменения в Google Sheets
    и уведомляет пользователей в Telegram
    """
    global _last_sheet_state
    
    while True:
        await asyncio.sleep(60)  # Проверяем каждую минуту
        try:
            sheet = get_sheet()
            all_rows = sheet.get_all_values()
            
            current_state = {}
            for row in all_rows[1:]:
                if row and row[0]:
                    task = row_to_task(row)
                    current_state[task["id"]] = task
            
            if _last_sheet_state:  # Пропускаем первый запуск
                # Ищем изменения
                for task_id, task in current_state.items():
                    if task_id in _last_sheet_state:
                        old = _last_sheet_state[task_id]
                        changes = []
                        status_labels = {"todo": "Новая", "doing": "В работе", "done": "Готово"}
                        priority_labels = {"high": "🔴 Высокий", "medium": "🟡 Средний", "low": "🟢 Низкий"}
                        
                        if old["title"] != task["title"]:
                            changes.append(f"📝 Название: *{task['title']}*")
                        if old["status"] != task["status"]:
                            changes.append(f"🔄 Статус: {status_labels.get(old['status'])} → *{status_labels.get(task['status'])}*")
                        if old["priority"] != task["priority"]:
                            changes.append(f"⚡ Приоритет: {priority_labels.get(task['priority'])}")
                        if old["deadline"] != task["deadline"]:
                            changes.append(f"📅 Дедлайн: *{task['deadline'] or 'убран'}*")
                        if old["assignee"] != task["assignee"]:
                            changes.append(f"👤 Исполнитель: *{task['assignee'] or 'не назначен'}*")
                        
                        if changes:
                            user_id = task["user_id"]
                            chat_id = user_chat_ids.get(user_id)
                            if chat_id:
                                msg = f"📊 *Изменение в Google Sheets*\n\nЗадача: *{task['title']}*\n\n" + "\n".join(changes)
                                await bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
                    else:
                        # Новая задача добавлена через Sheets
                        user_id = task["user_id"]
                        chat_id = user_chat_ids.get(user_id)
                        if chat_id:
                            msg = f"✅ *Новая задача из Google Sheets*\n\n*{task['title']}*"
                            if task["description"]:
                                msg += f"\n_{task['description']}_"
                            await bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
                
                # Удалённые задачи
                for task_id in _last_sheet_state:
                    if task_id not in current_state:
                        old = _last_sheet_state[task_id]
                        user_id = old["user_id"]
                        chat_id = user_chat_ids.get(user_id)
                        if chat_id:
                            msg = f"🗑 *Задача удалена из Google Sheets*\n\n~~{old['title']}~~"
                            await bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
            
            _last_sheet_state = current_state
            
        except Exception as e:
            logger.error(f"check_sheet_changes error: {e}")


# ==========================================
# DAILY REMINDERS
# ==========================================
async def send_daily_reminders():
    """
    Отправляет ежедневные уведомления о задачах
    Запускается каждый день в 9:00
    """
    while True:
        # Ждём до 9:00
        now = datetime.now()
        next_9am = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if now >= next_9am:
            next_9am += timedelta(days=1)
        
        wait_seconds = (next_9am - now).total_seconds()
        await asyncio.sleep(wait_seconds)
        
        try:
            sheet = get_sheet()
            all_rows = sheet.get_all_values()
            today = date.today()
            
            # Группируем задачи по пользователям
            user_tasks: dict[str, list] = {}
            for row in all_rows[1:]:
                if not row or not row[0]:
                    continue
                task = row_to_task(row)
                if task["status"] == "done":
                    continue
                
                user_id = task["user_id"]
                if user_id not in user_tasks:
                    user_tasks[user_id] = {"overdue": [], "today": [], "upcoming": []}
                
                if task["deadline"]:
                    try:
                        dl = date.fromisoformat(task["deadline"])
                        if dl < today:
                            user_tasks[user_id]["overdue"].append(task)
                        elif dl == today:
                            user_tasks[user_id]["today"].append(task)
                        elif dl <= today + timedelta(days=3):
                            user_tasks[user_id]["upcoming"].append(task)
                    except ValueError:
                        pass
                else:
                    if task["status"] == "doing":
                        user_tasks[user_id]["upcoming"].append(task)
            
            # Отправляем уведомления
            for user_id, buckets in user_tasks.items():
                chat_id = user_chat_ids.get(user_id)
                if not chat_id:
                    continue
                
                total_urgent = len(buckets["overdue"]) + len(buckets["today"])
                if total_urgent == 0 and len(buckets["upcoming"]) == 0:
                    continue
                
                lines = [f"☀️ *Доброе утро! Сводка на {today.strftime('%d.%m.%Y')}*\n"]
                
                if buckets["overdue"]:
                    lines.append(f"🔴 *Просрочено ({len(buckets['overdue'])}):*")
                    for t in buckets["overdue"][:5]:
                        lines.append(f"  • {t['title']} _{t['deadline']}_")
                
                if buckets["today"]:
                    lines.append(f"\n🟡 *Дедлайн сегодня ({len(buckets['today'])}):*")
                    for t in buckets["today"]:
                        lines.append(f"  • {t['title']}")
                
                if buckets["upcoming"]:
                    lines.append(f"\n🟢 *Ближайшие задачи ({len(buckets['upcoming'])}):*")
                    for t in buckets["upcoming"][:3]:
                        dl = f" _{t['deadline']}_" if t["deadline"] else ""
                        lines.append(f"  • {t['title']}{dl}")
                
                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton("📋 Открыть задачи", url=WEBAPP_URL)
                ]])
                
                await bot.send_message(
                    chat_id=chat_id,
                    text="\n".join(lines),
                    parse_mode="Markdown",
                    reply_markup=keyboard,
                )
        
        except Exception as e:
            logger.error(f"send_daily_reminders error: {e}")


# ==========================================
# TELEGRAM BOT HANDLERS
# ==========================================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    user_id = str(user.id)
    
    # Сохраняем chat_id
    user_chat_ids[user_id] = chat_id
    
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "📋 Открыть Task Manager",
            web_app={"url": WEBAPP_URL}
        )
    ]])
    
    await update.message.reply_text(
        f"👋 Привет, *{user.first_name}*\\!\n\n"
        "Я помогу управлять твоими задачами\\.\n\n"
        "📊 Все задачи синхронизируются с Google Sheets\n"
        "🔔 Ежедневные напоминания в 9:00\n"
        "✏️ Редактируй задачи прямо в таблице\\!",
        parse_mode="MarkdownV2",
        reply_markup=keyboard,
    )


async def cmd_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать список активных задач"""
    user_id = str(update.effective_user.id)
    chat_id = update.effective_chat.id
    user_chat_ids[user_id] = chat_id
    
    try:
        sheet = get_sheet()
        all_rows = sheet.get_all_values()
        
        active = []
        for row in all_rows[1:]:
            if not row or not row[0]:
                continue
            task = row_to_task(row)
            if task["user_id"] == user_id and task["status"] != "done":
                active.append(task)
        
        if not active:
            await update.message.reply_text("✅ Нет активных задач!")
            return
        
        status_icons = {"todo": "⚪", "doing": "🔵", "done": "✅"}
        priority_icons = {"high": "🔴", "medium": "🟡", "low": "🟢"}
        lines = [f"📋 *Активные задачи ({len(active)}):*\n"]
        
        for t in active[:10]:
            s = status_icons.get(t["status"], "•")
            p = priority_icons.get(t["priority"], "")
            dl = f" _({t['deadline']})_" if t["deadline"] else ""
            lines.append(f"{s}{p} {t['title']}{dl}")
        
        if len(active) > 10:
            lines.append(f"\n_... и ещё {len(active)-10} задач_")
        
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("📋 Открыть всё", web_app={"url": WEBAPP_URL})
        ]])
        
        await update.message.reply_text(
            "\n".join(lines), parse_mode="Markdown", reply_markup=keyboard
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика задач"""
    user_id = str(update.effective_user.id)
    
    try:
        sheet = get_sheet()
        all_rows = sheet.get_all_values()
        tasks = [row_to_task(r) for r in all_rows[1:] if r and r[0] and row_to_task(r)["user_id"] == user_id]
        
        total = len(tasks)
        by_status = {"todo": 0, "doing": 0, "done": 0}
        overdue = 0
        today = date.today()
        
        for t in tasks:
            by_status[t["status"]] = by_status.get(t["status"], 0) + 1
            if t["deadline"] and t["status"] != "done":
                try:
                    if date.fromisoformat(t["deadline"]) < today:
                        overdue += 1
                except ValueError:
                    pass
        
        done_pct = round(by_status["done"] / total * 100) if total else 0
        
        msg = (
            f"📊 *Твоя статистика*\n\n"
            f"Всего задач: *{total}*\n"
            f"├ ⚪ Новые: {by_status['todo']}\n"
            f"├ 🔵 В работе: {by_status['doing']}\n"
            f"└ ✅ Готово: {by_status['done']}\n\n"
            f"🔴 Просрочено: {overdue}\n"
            f"📈 Выполнено: {done_pct}%"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*Команды:*\n\n"
        "/start — открыть Task Manager\n"
        "/tasks — список активных задач\n"
        "/stats — статистика\n"
        "/help — помощь\n\n"
        "_Уведомления приходят в 9:00 каждый день_",
        parse_mode="Markdown",
    )


def _log_change(user_id, user_name, action, task_id, task_title, changes):
    """Логирует изменение в отдельный лист"""
    try:
        log_sheet = get_sheet(LOG_SHEET_NAME)
        log_sheet.append_row([
            datetime.now().isoformat(timespec="seconds"),
            user_id, user_name, action, task_id, task_title, changes
        ])
    except Exception as e:
        logger.warning(f"Log error: {e}")


# ==========================================
# STARTUP
# ==========================================
@app.on_event("startup")
async def startup():
    # Инициализируем Google Sheets
    try:
        sheet = get_sheet()
        logger.info(f"✅ Google Sheets connected: {sheet.title}")
    except Exception as e:
        logger.error(f"❌ Google Sheets error: {e}")
    
    # Запускаем фоновые задачи
    asyncio.create_task(check_sheet_changes())
    asyncio.create_task(send_daily_reminders())
    logger.info("✅ Background tasks started")


@app.on_event("shutdown")
async def shutdown():
    await bot.close()


# ==========================================
# TELEGRAM WEBHOOK
# ==========================================
telegram_app = None

@app.post("/webhook/{token}")
async def telegram_webhook(token: str, request: Request):
    if token != BOT_TOKEN:
        raise HTTPException(status_code=403)
    
    global telegram_app
    if telegram_app is None:
        telegram_app = (
            Application.builder()
            .token(BOT_TOKEN)
            .build()
        )
        telegram_app.add_handler(CommandHandler("start", cmd_start))
        telegram_app.add_handler(CommandHandler("tasks", cmd_tasks))
        telegram_app.add_handler(CommandHandler("stats", cmd_stats))
        telegram_app.add_handler(CommandHandler("help", cmd_help))
        await telegram_app.initialize()
    
    data = await request.json()
    update = Update.de_json(data, bot)
    await telegram_app.process_update(update)
    return {"ok": True}


@app.get("/health")
async def health():
    return {"status": "ok", "time": datetime.now().isoformat()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
