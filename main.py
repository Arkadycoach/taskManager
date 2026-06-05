"""
Task Manager Bot — исправленный бэкенд
✅ Уведомления теперь реально приходят
✅ Webhook регистрируется автоматически
✅ chat_id сохраняется в Sheets (не теряется при рестарте)
✅ Богатые кнопки в боте
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, date
from typing import Optional

import gspread
import httpx
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from google.oauth2.service_account import Credentials
from pydantic import BaseModel
from telegram import (Bot, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update)
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                           ContextTypes, MessageHandler, filters)

# ══════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════
BOT_TOKEN         = os.getenv("BOT_TOKEN", "")
WEBAPP_URL        = os.getenv("WEBAPP_URL", "https://your-frontend-url.com")
SERVER_URL        = os.getenv("SERVER_URL", "")      # https://taskmanager-production-6032.up.railway.app
SHEET_ID          = os.getenv("SHEET_ID", "")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON", "")

# ★ ГЛАВНЫЙ FIX: твой Telegram user_id = chat_id для личных сообщений
# Узнать: напиши @userinfobot
MY_TELEGRAM_ID = int(os.getenv("MY_TELEGRAM_ID", "0"))

SHEET_NAME     = "Tasks"
LOG_SHEET_NAME = "ChangeLog"
SETTINGS_SHEET = "Settings"

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

COLUMNS = [
    "ID", "Title", "Description", "Status", "Priority",
    "Deadline", "Assignee", "UserID", "UserName", "CreatedAt", "UpdatedAt"
]

STATUS_RU   = {"todo": "Новая",   "doing": "В работе", "done": "Готово"}
STATUS_EN   = {"Новая": "todo",   "В работе": "doing", "Готово": "done"}
PRIO_RU     = {"low": "Низкий",  "medium": "Средний", "high": "Высокий"}
PRIO_EN     = {"Низкий": "low",  "Средний": "medium", "Высокий": "high"}
STATUS_ICON = {"todo": "🔵", "doing": "🟡", "done": "✅"}
PRIO_ICON   = {"high": "🔴", "medium": "🟡", "low": "🟢"}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════
# GOOGLE SHEETS
# ══════════════════════════════════════════════════════════
def get_sheets_client():
    d = json.loads(GOOGLE_CREDS_JSON) if GOOGLE_CREDS_JSON else json.load(open("service_account.json"))
    return gspread.authorize(Credentials.from_service_account_info(d, scopes=SCOPES))

def get_sheet(name=SHEET_NAME):
    sp = get_sheets_client().open_by_key(SHEET_ID)
    try:
        return sp.worksheet(name)
    except gspread.WorksheetNotFound:
        s = sp.add_worksheet(title=name, rows=1000, cols=len(COLUMNS))
        if name == SHEET_NAME:
            s.append_row(COLUMNS)
        elif name == LOG_SHEET_NAME:
            s.append_row(["Time","UserID","User","Action","TaskID","Title","Changes"])
        elif name == SETTINGS_SHEET:
            s.append_row(["Key","Value"])
        return s

def row_to_task(row: list) -> dict:
    def g(i): return row[i] if i < len(row) else ""
    raw_s, raw_p = g(3), g(4)
    return {
        "id": g(0), "title": g(1), "description": g(2),
        "status":   STATUS_EN.get(raw_s) or (raw_s if raw_s in STATUS_RU else "todo"),
        "priority": PRIO_EN.get(raw_p)   or (raw_p if raw_p in PRIO_RU   else "medium"),
        "deadline": g(5), "assignee": g(6),
        "user_id": g(7), "user_name": g(8),
        "created_at": g(9), "updated_at": g(10),
    }

def get_all_tasks():
    rows = get_sheet().get_all_values()
    return [row_to_task(r) for r in rows[1:] if r and r[0] and len(r) > 1]

# ══════════════════════════════════════════════════════════
# CHAT_ID PERSISTENCE  ← FIX #1
# Сохраняем chat_id в Google Sheets — не теряется при рестарте
# ══════════════════════════════════════════════════════════
_chat_ids: dict[str, int] = {}   # user_id → chat_id (in-memory cache)

def _save_chat_id(user_id: str, chat_id: int):
    """Сохранить в памяти и в Sheets."""
    _chat_ids[user_id] = chat_id
    try:
        s    = get_sheet(SETTINGS_SHEET)
        rows = s.get_all_values()
        key  = f"chat_id:{user_id}"
        for i, row in enumerate(rows[1:], start=2):
            if row and row[0] == key:
                s.update_cell(i, 2, str(chat_id))
                return
        s.append_row([key, str(chat_id)])
    except Exception as e:
        logger.warning(f"_save_chat_id: {e}")

def _load_chat_ids():
    """Загрузить chat_ids из Sheets при старте."""
    try:
        s    = get_sheet(SETTINGS_SHEET)
        rows = s.get_all_values()
        for row in rows[1:]:
            if row and len(row) >= 2 and row[0].startswith("chat_id:"):
                uid = row[0].replace("chat_id:", "")
                try:
                    _chat_ids[uid] = int(row[1])
                except ValueError:
                    pass
        logger.info(f"Loaded {len(_chat_ids)} chat_ids from Sheets")
    except Exception as e:
        logger.warning(f"_load_chat_ids: {e}")

def _get_notify_chat_id() -> Optional[int]:
    """
    Получить chat_id для уведомлений.
    FIX: для личных чатов user_id == chat_id!
    Если MY_TELEGRAM_ID задан — используем его напрямую.
    """
    # ★ Прямой способ: user_id == chat_id для личных сообщений
    if MY_TELEGRAM_ID:
        return MY_TELEGRAM_ID

    # Резерв: из реестра зарегистрированных пользователей
    if _chat_ids:
        return list(_chat_ids.values())[0]
    return None

# ══════════════════════════════════════════════════════════
# FASTAPI
# ══════════════════════════════════════════════════════════
app = FastAPI(title="Task Manager API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
bot = Bot(token=BOT_TOKEN)

# ── Pydantic models ────────────────────────────────────────
class TaskCreate(BaseModel):
    title: str; description: str = ""; status: str = "todo"
    priority: str = "medium"; deadline: str = ""; assignee: str = ""
    user_id: str = ""; user_name: str = ""

class TaskUpdate(BaseModel):
    title: Optional[str] = None; description: Optional[str] = None
    status: Optional[str] = None; priority: Optional[str] = None
    deadline: Optional[str] = None; assignee: Optional[str] = None
    user_id: str = ""; user_name: str = ""

class SubtaskCreate(BaseModel):
    title: str; user_id: str = ""

class SubtaskUpdate(BaseModel):
    title: Optional[str] = None; status: Optional[str] = None

class CommentCreate(BaseModel):
    text: str; user_id: str = ""; user_name: str = ""

# ── Tasks CRUD ─────────────────────────────────────────────
@app.get("/tasks")
async def get_tasks():
    try:
        return {"tasks": get_all_tasks()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/tasks")
async def create_task(task: TaskCreate, x_user_id: str = Header(default="")):
    try:
        s   = get_sheet()
        tid = str(uuid.uuid4())[:8].upper()
        now = datetime.now().isoformat(timespec="seconds")
        uid = task.user_id or x_user_id
        s.append_row([tid, task.title, task.description,
                      STATUS_RU.get(task.status, task.status),
                      PRIO_RU.get(task.priority, task.priority),
                      task.deadline, task.assignee, uid, task.user_name, now, now])
        new = {"id":tid,"title":task.title,"description":task.description,"status":task.status,
               "priority":task.priority,"deadline":task.deadline,"assignee":task.assignee,
               "user_id":uid,"user_name":task.user_name,"created_at":now,"updated_at":now}
        _log(uid, task.user_name, "CREATE", tid, task.title, "Создана")
        await _notify("create", new)
        return {"task": new}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/tasks/{tid}")
async def update_task(tid: str, upd: TaskUpdate, x_user_id: str = Header(default="")):
    try:
        s    = get_sheet(); rows = s.get_all_values()
        idx  = None; old = None
        for i, row in enumerate(rows[1:], start=2):
            if row and row[0] == tid: idx=i; old=row_to_task(row); break
        if not idx: raise HTTPException(status_code=404, detail="Not found")

        changes = []
        if upd.title       is not None: s.update_cell(idx,2,upd.title);           old["title"]!=upd.title   and changes.append(f"Название → {upd.title}")
        if upd.description is not None: s.update_cell(idx,3,upd.description)
        if upd.status      is not None: s.update_cell(idx,4,STATUS_RU.get(upd.status,upd.status)); old["status"]!=upd.status and changes.append(f"Статус → {STATUS_RU.get(upd.status)}")
        if upd.priority    is not None: s.update_cell(idx,5,PRIO_RU.get(upd.priority,upd.priority)); old["priority"]!=upd.priority and changes.append(f"Приоритет → {PRIO_RU.get(upd.priority)}")
        if upd.deadline    is not None: s.update_cell(idx,6,upd.deadline);         old["deadline"]!=upd.deadline and changes.append(f"Дедлайн → {upd.deadline or 'убран'}")
        if upd.assignee    is not None: s.update_cell(idx,7,upd.assignee);         old["assignee"]!=upd.assignee and changes.append(f"Исполнитель → {upd.assignee or '—'}")
        now = datetime.now().isoformat(timespec="seconds"); s.update_cell(idx,11,now)

        updated = {**old, **{k:v for k,v in {"title":upd.title,"description":upd.description,"status":upd.status,"priority":upd.priority,"deadline":upd.deadline,"assignee":upd.assignee}.items() if v is not None}}
        uid = upd.user_id or x_user_id
        if changes:
            _log(uid, upd.user_name, "UPDATE", tid, upd.title or old["title"], "; ".join(changes))
            await _notify("update", updated, changes)
        if upd.status == "done" and old["status"] != "done":
            await _notify("done", updated)
        return {"success": True}
    except HTTPException: raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/tasks/{tid}")
async def delete_task(tid: str, x_user_id: str = Header(default="")):
    try:
        s = get_sheet(); rows = s.get_all_values()
        for i, row in enumerate(rows[1:], start=2):
            if row and row[0] == tid:
                t = row_to_task(row); s.delete_rows(i)
                _log(x_user_id,"","DELETE",tid,row[1] if len(row)>1 else "","Удалена")
                await _notify("delete", t)
                return {"success": True}
        raise HTTPException(status_code=404, detail="Not found")
    except HTTPException: raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Subtasks ───────────────────────────────────────────────
def _sub_sheet():
    sp = get_sheets_client().open_by_key(SHEET_ID)
    try: return sp.worksheet("Subtasks")
    except gspread.WorksheetNotFound:
        s = sp.add_worksheet(title="Subtasks", rows=2000, cols=6)
        s.append_row(["SubID","ParentID","Title","Status","CreatedAt","UpdatedAt"])
        return s

def _com_sheet():
    sp = get_sheets_client().open_by_key(SHEET_ID)
    try: return sp.worksheet("Comments")
    except gspread.WorksheetNotFound:
        s = sp.add_worksheet(title="Comments", rows=5000, cols=6)
        s.append_row(["CommentID","TaskID","UserID","UserName","Text","CreatedAt"])
        return s

@app.get("/tasks/{tid}/subtasks")
async def get_subtasks(tid: str):
    try:
        rows = _sub_sheet().get_all_values()
        subs = [{"id":r[0],"parent_id":r[1],"title":r[2],"status":r[3],"created_at":r[4]}
                for r in rows[1:] if len(r)>1 and r[1]==tid and r[0]]
        return {"subtasks": subs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/tasks/{tid}/subtasks")
async def create_subtask(tid: str, sub: SubtaskCreate):
    try:
        s   = _sub_sheet(); sid = str(uuid.uuid4())[:8].upper()
        now = datetime.now().isoformat(timespec="seconds")
        s.append_row([sid, tid, sub.title, "todo", now, now])
        return {"subtask":{"id":sid,"parent_id":tid,"title":sub.title,"status":"todo","created_at":now}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/subtasks/{sid}")
async def update_subtask(sid: str, upd: SubtaskUpdate):
    try:
        s = _sub_sheet(); rows = s.get_all_values()
        for i, row in enumerate(rows[1:], start=2):
            if row and row[0] == sid:
                if upd.title  is not None: s.update_cell(i,3,upd.title)
                if upd.status is not None: s.update_cell(i,4,upd.status)
                s.update_cell(i,6,datetime.now().isoformat(timespec="seconds"))
                return {"success": True}
        raise HTTPException(status_code=404, detail="Not found")
    except HTTPException: raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/subtasks/{sid}")
async def delete_subtask(sid: str):
    try:
        s = _sub_sheet(); rows = s.get_all_values()
        for i, row in enumerate(rows[1:], start=2):
            if row and row[0] == sid: s.delete_rows(i); return {"success": True}
        raise HTTPException(status_code=404, detail="Not found")
    except HTTPException: raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Comments ───────────────────────────────────────────────
@app.get("/tasks/{tid}/comments")
async def get_comments(tid: str):
    try:
        rows = _com_sheet().get_all_values()
        coms = [{"id":r[0],"task_id":r[1],"user_id":r[2],"user_name":r[3],"text":r[4],"created_at":r[5]}
                for r in rows[1:] if len(r)>1 and r[1]==tid and r[0]]
        return {"comments": coms}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/tasks/{tid}/comments")
async def create_comment(tid: str, com: CommentCreate):
    try:
        s = _com_sheet(); cid = str(uuid.uuid4())[:8].upper()
        now = datetime.now().isoformat(timespec="seconds")
        s.append_row([cid, tid, com.user_id, com.user_name, com.text, now])
        return {"comment":{"id":cid,"task_id":tid,"user_id":com.user_id,"user_name":com.user_name,"text":com.text,"created_at":now}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/comments/{cid}")
async def delete_comment(cid: str):
    try:
        s = _com_sheet(); rows = s.get_all_values()
        for i, row in enumerate(rows[1:], start=2):
            if row and row[0] == cid: s.delete_rows(i); return {"success": True}
        raise HTTPException(status_code=404, detail="Not found")
    except HTTPException: raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/register")
async def register_user(data: dict):
    uid = str(data.get("user_id",""))
    cid = data.get("chat_id")
    if uid and cid: _save_chat_id(uid, int(cid))
    return {"ok": True}

@app.get("/health")
async def health():
    chat_id = _get_notify_chat_id()
    return {
        "status": "ok",
        "time":   datetime.now().isoformat(),
        "MY_TELEGRAM_ID": MY_TELEGRAM_ID,
        "notify_chat_id": chat_id,
        "registered_users": len(_chat_ids),
        "webhook_url": f"{SERVER_URL}/webhook/{BOT_TOKEN[:8]}..." if SERVER_URL else "not set"
    }

# ══════════════════════════════════════════════════════════
# NOTIFICATIONS  ← FIX #2: используем MY_TELEGRAM_ID напрямую
# ══════════════════════════════════════════════════════════
async def _notify(event: str, task: dict, changes: list = None):
    chat_id = _get_notify_chat_id()
    if not chat_id:
        logger.warning("⚠️  Нет chat_id для уведомлений. "
                       "Убедись что: 1) MY_TELEGRAM_ID задан в Railway, "
                       "2) ты отправил /start боту хотя бы раз.")
        return

    si = STATUS_ICON.get(task.get("status","todo"), "🔵")
    pi = PRIO_ICON.get(task.get("priority","medium"), "🟡")
    title = task.get("title", "")
    tid   = task.get("id", "")
    dl    = task.get("deadline","")
    asgn  = task.get("assignee","")
    dl_str   = f"\n📅 *Дедлайн:* {dl}"  if dl   else ""
    asgn_str = f"\n👤 *Исполнитель:* {asgn}" if asgn else ""

    if event == "create":
        text = (f"✅ *Задача создана*\n\n{pi} *{title}*\n"
                f"{si} {STATUS_RU.get(task.get('status','todo'))}"
                f"{dl_str}{asgn_str}")
    elif event == "done":
        text = f"🎉 *Выполнено!*\n\n✅ *{title}*\n\nОтличная работа! 💪"
    elif event == "update":
        ch = "\n".join(f"  • {c}" for c in (changes or []))
        text = f"✏️ *Задача обновлена*\n\n*{title}*\n\n{ch}"
    elif event == "delete":
        text = f"🗑 *Задача удалена*\n\n~~{title}~~"
    elif event == "sheets_update":
        ch = "\n".join(f"  • {c}" for c in (changes or []))
        text = f"📊 *Изменение в Google Sheets*\n\n*{title}*\n\n{ch}"
    else:
        return

    # Кнопки действий для активных задач
    kb = None
    if event in ("create", "update", "sheets_update") and tid:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("▶️ В работу",  callback_data=f"s:doing:{tid}"),
             InlineKeyboardButton("✅ Выполнено", callback_data=f"s:done:{tid}")],
            [InlineKeyboardButton("🌐 Открыть приложение", url=WEBAPP_URL)],
        ])
    elif event == "done":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Все задачи", callback_data="m:tasks")],
            [InlineKeyboardButton("🌐 Открыть приложение", url=WEBAPP_URL)],
        ])

    try:
        await bot.send_message(chat_id=chat_id, text=text,
                               parse_mode="Markdown", reply_markup=kb)
        logger.info(f"✅ Уведомление отправлено в {chat_id}: {event} / {title}")
    except Exception as e:
        logger.error(f"❌ Не удалось отправить уведомление: {e}")

# ══════════════════════════════════════════════════════════
# WEBHOOK SETUP  ← FIX #3: авторегистрация при старте
# ══════════════════════════════════════════════════════════
async def setup_webhook():
    if not SERVER_URL:
        logger.warning("⚠️  SERVER_URL не задан — webhook не будет зарегистрирован автоматически.")
        logger.info("Зарегистрируй вручную: GET /setup_webhook")
        return
    webhook_url = f"{SERVER_URL}/webhook/{BOT_TOKEN}"
    try:
        result = await bot.set_webhook(
            url=webhook_url,
            allowed_updates=["message", "callback_query"],
            drop_pending_updates=True,
        )
        if result:
            logger.info(f"✅ Webhook зарегистрирован: {webhook_url}")
        else:
            logger.error("❌ Webhook не зарегистрирован")
    except Exception as e:
        logger.error(f"❌ setup_webhook: {e}")

@app.get("/setup_webhook")
async def setup_webhook_endpoint():
    """Вызови этот URL вручную если автоматическая регистрация не сработала."""
    if not SERVER_URL:
        return {"error": "SERVER_URL не задан в переменных окружения Railway"}
    webhook_url = f"{SERVER_URL}/webhook/{BOT_TOKEN}"
    try:
        result = await bot.set_webhook(url=webhook_url, drop_pending_updates=True)
        info   = await bot.get_webhook_info()
        return {"success": result, "webhook_url": webhook_url, "info": str(info)}
    except Exception as e:
        return {"error": str(e)}

@app.get("/webhook_info")
async def webhook_info():
    """Проверь текущий статус webhook."""
    try:
        info = await bot.get_webhook_info()
        return {
            "url": info.url,
            "pending_update_count": info.pending_update_count,
            "last_error": info.last_error_message,
            "MY_TELEGRAM_ID": MY_TELEGRAM_ID,
            "notify_chat_id": _get_notify_chat_id(),
        }
    except Exception as e:
        return {"error": str(e)}

# ══════════════════════════════════════════════════════════
# BOT COMMANDS  ← Богатые кнопки и удобное меню
# ══════════════════════════════════════════════════════════
def _main_menu_kb() -> InlineKeyboardMarkup:
    """Главное меню бота."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Открыть приложение", web_app={"url": WEBAPP_URL})],
        [InlineKeyboardButton("📋 Мои задачи",      callback_data="m:tasks"),
         InlineKeyboardButton("📅 Сегодня",         callback_data="m:today")],
        [InlineKeyboardButton("🔴 Просроченные",    callback_data="m:overdue"),
         InlineKeyboardButton("📊 Статистика",      callback_data="m:stats")],
        [InlineKeyboardButton("➕ Добавить задачу", callback_data="m:add")],
    ])

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    chat_id = update.effective_chat.id
    uid     = str(user.id)

    # ★ Сохраняем chat_id — это ключевой шаг для уведомлений
    _save_chat_id(uid, chat_id)
    logger.info(f"✅ Зарегистрирован пользователь {uid} → chat_id {chat_id}")

    await bot.set_my_commands([
        BotCommand("start",   "🏠 Главное меню"),
        BotCommand("tasks",   "📋 Активные задачи"),
        BotCommand("today",   "📅 Дедлайны сегодня"),
        BotCommand("overdue", "🔴 Просроченные"),
        BotCommand("add",     "➕ Добавить задачу"),
        BotCommand("done",    "✅ Выполнить задачу"),
        BotCommand("stats",   "📊 Статистика"),
        BotCommand("help",    "❓ Помощь"),
    ])

    # Считаем статистику
    try:
        tasks    = get_all_tasks()
        total    = len(tasks)
        active   = sum(1 for t in tasks if t["status"] != "done")
        done     = sum(1 for t in tasks if t["status"] == "done")
        today    = date.today()
        overdue  = sum(1 for t in tasks if t["deadline"] and t["status"] != "done"
                       and _safe_date(t["deadline"]) < today)
        td_count = sum(1 for t in tasks if t["deadline"] and t["status"] != "done"
                       and _safe_date(t["deadline"]) == today)
        pct      = round(done / total * 100) if total else 0

        stats_line = (f"\n\n📊 *Сводка:*\n"
                      f"├ 📋 Всего: *{total}*  ✅ Готово: *{done}* ({pct}%)\n"
                      f"├ 🔵 Активных: *{active}*")
        if overdue:  stats_line += f"\n├ 🔴 Просрочено: *{overdue}*"
        if td_count: stats_line += f"\n└ 📅 Сегодня: *{td_count}*"
    except Exception:
        stats_line = ""

    await update.message.reply_text(
        f"👋 Привет, *{user.first_name}*\\!"
        f"\n\nДобро пожаловать в Task Manager\\."
        f"{stats_line.replace('*','\\*').replace('_','\\_') if stats_line else ''}\n\n"
        "Выбери действие:",
        parse_mode="MarkdownV2",
        reply_markup=_main_menu_kb(),
    )

async def cmd_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список активных задач с кнопками."""
    uid = str(update.effective_user.id)
    _save_chat_id(uid, update.effective_chat.id)
    await _send_task_list(update.message, "all")

async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    _save_chat_id(uid, update.effective_chat.id)
    await _send_task_list(update.message, "today")

async def cmd_overdue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    _save_chat_id(uid, update.effective_chat.id)
    await _send_task_list(update.message, "overdue")

async def _send_task_list(message, filter_type: str):
    """Отправить список задач с кнопками действий."""
    try:
        tasks    = get_all_tasks()
        today    = date.today()

        if filter_type == "all":
            filtered = [t for t in tasks if t["status"] != "done"]
            header   = f"📋 *Активные задачи ({len(filtered)})*"
        elif filter_type == "today":
            filtered = [t for t in tasks if t["deadline"] and t["status"] != "done"
                        and _safe_date(t["deadline"]) == today]
            header   = f"📅 *Дедлайн сегодня ({len(filtered)})*"
        elif filter_type == "overdue":
            filtered = [t for t in tasks if t["deadline"] and t["status"] != "done"
                        and _safe_date(t["deadline"]) < today]
            header   = f"🔴 *Просроченные ({len(filtered)})*"
        else:
            filtered = [t for t in tasks if t["status"] != "done"]
            header   = f"📋 *Задачи ({len(filtered)})*"

        if not filtered:
            await message.reply_text(
                "🎉 *Нет задач в этой категории!*",
                parse_mode="Markdown",
                reply_markup=_main_menu_kb(),
            )
            return

        # Показываем задачи по 5, с кнопками для каждой
        for chunk_start in range(0, min(len(filtered), 10), 5):
            chunk = filtered[chunk_start:chunk_start + 5]
            lines = [header if chunk_start == 0 else f"_(продолжение)_", ""]

            rows = []
            for t in chunk:
                si   = STATUS_ICON.get(t["status"], "•")
                pi   = PRIO_ICON.get(t["priority"], "")
                dl   = f"📅 {t['deadline']}" if t["deadline"] else ""
                asgn = f"👤 {t['assignee']}" if t["assignee"] else ""
                meta = "  ".join(filter(None, [dl, asgn]))
                lines.append(f"{si}{pi} *{t['title']}*")
                if meta: lines.append(f"   {meta}")

                # Кнопки для каждой задачи
                btns = []
                if t["status"] != "doing": btns.append(InlineKeyboardButton("▶️ В работу", callback_data=f"s:doing:{t['id']}"))
                if t["status"] != "done":  btns.append(InlineKeyboardButton("✅ Готово",   callback_data=f"s:done:{t['id']}"))
                rows.append(btns)

            rows.append([InlineKeyboardButton("🏠 Меню", callback_data="m:main"),
                         InlineKeyboardButton("🌐 Приложение", url=WEBAPP_URL)])

            await message.reply_text(
                "\n".join(lines),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(rows),
            )

    except Exception as e:
        logger.error(f"_send_task_list: {e}")
        await message.reply_text("❌ Ошибка загрузки задач")

async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/add Название задачи !высокий @кто 2025-06-15"""
    import re
    uid   = str(update.effective_user.id)
    uname = update.effective_user.username or update.effective_user.first_name
    _save_chat_id(uid, update.effective_chat.id)

    if not context.args:
        await update.message.reply_text(
            "➕ *Добавить задачу:*\n\n"
            "`/add Название !приоритет @исполнитель 2025-06-15`\n\n"
            "*Приоритет:* `!высокий` · `!средний` · `!низкий`\n\n"
            "*Примеры:*\n"
            "`/add Написать отчёт !высокий`\n"
            "`/add Встреча @ivan 2025-06-10`",
            parse_mode="Markdown"
        )
        return

    raw      = " ".join(context.args)
    priority = "medium"; assignee = ""; deadline = ""

    for key, val in {"!высокий":"high","!срочно":"high","!средний":"medium","!низкий":"low"}.items():
        if key in raw.lower():
            priority = val; raw = re.sub(re.escape(key), "", raw, flags=re.IGNORECASE)

    m = re.search(r"@(\S+)", raw)
    if m: assignee = m.group(1); raw = raw.replace(m.group(0), "")
    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", raw)
    if m: deadline = m.group(1); raw = raw.replace(m.group(0), "")
    title = raw.strip()

    if not title:
        await update.message.reply_text("❌ Укажи название задачи.")
        return

    s   = get_sheet(); tid = str(uuid.uuid4())[:8].upper()
    now = datetime.now().isoformat(timespec="seconds")
    s.append_row([tid, title, "", STATUS_RU["todo"], PRIO_RU[priority],
                  deadline, assignee, uid, uname, now, now])

    pi   = PRIO_ICON[priority]
    dl   = f"\n📅 {deadline}" if deadline else ""
    asn  = f"\n👤 @{assignee}" if assignee else ""
    task = {"id":tid,"title":title,"status":"todo","priority":priority,"deadline":deadline,"assignee":assignee}
    await _notify("create", task)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ В работу", callback_data=f"s:doing:{tid}"),
         InlineKeyboardButton("✅ Выполнено", callback_data=f"s:done:{tid}")],
        [InlineKeyboardButton("📋 Все задачи", callback_data="m:tasks")],
    ])
    await update.message.reply_text(
        f"✅ *Задача добавлена!*\n\n{pi} *{title}*{dl}{asn}\n🆔 `{tid}`",
        parse_mode="Markdown", reply_markup=kb
    )

async def cmd_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/done ID_или_название"""
    uid = str(update.effective_user.id)
    _save_chat_id(uid, update.effective_chat.id)

    if not context.args:
        await update.message.reply_text("Формат: `/done ID_или_часть_названия`", parse_mode="Markdown")
        return

    query = " ".join(context.args).strip()
    s     = get_sheet(); rows = s.get_all_values()
    for i, row in enumerate(rows[1:], start=2):
        if not row or not row[0]: continue
        if row[0].upper() == query.upper() or (row[1] and query.lower() in row[1].lower()):
            task = row_to_task(row)
            s.update_cell(i, 4, "Готово")
            s.update_cell(i, 11, datetime.now().isoformat(timespec="seconds"))
            await _notify("done", task)
            await update.message.reply_text(
                f"🎉 *Выполнено!*\n\n✅ {task['title']}",
                parse_mode="Markdown",
                reply_markup=_main_menu_kb()
            )
            return
    await update.message.reply_text(f"❌ Задача «{query}» не найдена.\n/tasks — посмотреть все")

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    _save_chat_id(uid, update.effective_chat.id)
    await update.message.reply_text(
        await _stats_text(),
        parse_mode="Markdown",
        reply_markup=_main_menu_kb()
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❓ *Task Manager — справка*\n\n"
        "*Команды:*\n"
        "/start — 🏠 Главное меню\n"
        "/tasks — 📋 Активные задачи\n"
        "/today — 📅 Дедлайны сегодня\n"
        "/overdue — 🔴 Просроченные\n"
        "/add Название \\!приоритет @кто — ➕ Добавить\n"
        "/done ID — ✅ Выполнить задачу\n"
        "/stats — 📊 Статистика\n\n"
        "*Уведомления приходят когда:*\n"
        "• ✅ Создана задача\n"
        "• ✏️ Изменена задача\n"
        "• 🎉 Задача выполнена\n"
        "• 📊 Изменение в Google Sheets\n"
        "• ☀️ Утренний дайджест в 9:00\n\n"
        "*Если уведомления не приходят:*\n"
        "1\\. Убедись что `MY_TELEGRAM_ID` задан в Railway\n"
        "2\\. Напиши /start боту\n"
        "3\\. Проверь `/webhook_info`",
        parse_mode="MarkdownV2",
        reply_markup=_main_menu_kb()
    )

async def _stats_text() -> str:
    tasks   = get_all_tasks()
    today   = date.today()
    total   = len(tasks)
    by_s    = {"todo":0,"doing":0,"done":0}
    overdue = 0
    for t in tasks:
        by_s[t["status"]] = by_s.get(t["status"],0)+1
        if t["deadline"] and t["status"]!="done" and _safe_date(t["deadline"])<today: overdue+=1
    pct = round(by_s["done"]/total*100) if total else 0
    bar = "█"*round(pct/10) + "░"*(10-round(pct/10))
    return (f"📊 *Статистика задач*\n\n"
            f"[{bar}] *{pct}%*\n\n"
            f"📋 Всего: *{total}*\n"
            f"├ 🔵 Новых: {by_s['todo']}\n"
            f"├ 🟡 В работе: {by_s['doing']}\n"
            f"└ ✅ Готово: {by_s['done']}\n\n"
            f"🔴 Просрочено: *{overdue}*")

def _safe_date(s: str) -> date:
    try: return date.fromisoformat(s)
    except: return date(9999,1,1)

# ══════════════════════════════════════════════════════════
# CALLBACK ROUTER  ← Обработка нажатий на кнопки
# ══════════════════════════════════════════════════════════
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    await q.answer()
    data = q.data or ""

    try:
        # ── Меню ────────────────────────────────────────────
        if data == "m:main":
            tasks    = get_all_tasks()
            total    = len(tasks)
            done_cnt = sum(1 for t in tasks if t["status"]=="done")
            pct      = round(done_cnt/total*100) if total else 0
            await q.edit_message_text(
                f"🏠 *Главное меню*\n\n"
                f"Задач: *{total}* | Выполнено: *{done_cnt}* ({pct}%)",
                parse_mode="Markdown",
                reply_markup=_main_menu_kb()
            )

        elif data == "m:tasks":
            await q.edit_message_text("📋 Загружаю задачи...", parse_mode="Markdown")
            await _send_task_list(q.message, "all")

        elif data == "m:today":
            await q.edit_message_text("📅 Загружаю...", parse_mode="Markdown")
            await _send_task_list(q.message, "today")

        elif data == "m:overdue":
            await q.edit_message_text("🔴 Загружаю...", parse_mode="Markdown")
            await _send_task_list(q.message, "overdue")

        elif data == "m:stats":
            text = await _stats_text()
            await q.edit_message_text(text, parse_mode="Markdown", reply_markup=_main_menu_kb())

        elif data == "m:add":
            await q.edit_message_text(
                "➕ *Добавить задачу*\n\n"
                "Используй команду:\n"
                "`/add Название !приоритет @кто 2025-06-15`\n\n"
                "*Примеры:*\n"
                "`/add Написать отчёт !высокий`\n"
                "`/add Встреча с клиентом @ivan 2025-06-10`",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🏠 Меню", callback_data="m:main"),
                    InlineKeyboardButton("🌐 Приложение", url=WEBAPP_URL),
                ]])
            )

        # ── Смена статуса ────────────────────────────────────
        elif data.startswith("s:"):
            parts      = data.split(":")
            new_status = parts[1]; tid = parts[2]
            s          = get_sheet(); rows = s.get_all_values()
            for i, row in enumerate(rows[1:], start=2):
                if row and row[0] == tid:
                    task = row_to_task(row)
                    s.update_cell(i, 4, STATUS_RU.get(new_status, new_status))
                    s.update_cell(i, 11, datetime.now().isoformat(timespec="seconds"))
                    task["status"] = new_status
                    si   = STATUS_ICON.get(new_status,"🔵")
                    sl   = STATUS_RU.get(new_status, new_status)

                    if new_status == "done":
                        await _notify("done", task)
                        await q.edit_message_text(
                            f"🎉 *Выполнено!*\n\n✅ *{task['title']}*",
                            parse_mode="Markdown",
                            reply_markup=InlineKeyboardMarkup([[
                                InlineKeyboardButton("📋 Все задачи", callback_data="m:tasks"),
                                InlineKeyboardButton("🏠 Меню",      callback_data="m:main"),
                            ]])
                        )
                    else:
                        await q.edit_message_text(
                            f"{si} *{sl}*\n\n*{task['title']}*",
                            parse_mode="Markdown",
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("✅ Выполнено", callback_data=f"s:done:{tid}"),
                                 InlineKeyboardButton("📋 К списку",  callback_data="m:tasks")],
                            ])
                        )
                    return
            await q.edit_message_text("❌ Задача не найдена.")

    except Exception as e:
        logger.error(f"callback '{data}': {e}")

# ══════════════════════════════════════════════════════════
# SHEETS POLLING
# ══════════════════════════════════════════════════════════
_last_state: dict = {}

async def check_sheet_changes():
    global _last_state
    while True:
        await asyncio.sleep(60)
        try:
            tasks   = get_all_tasks()
            current = {t["id"]: t for t in tasks}

            if _last_state:
                for tid, task in current.items():
                    if tid in _last_state:
                        old = _last_state[tid]; changes = []
                        if old["title"]    != task["title"]:    changes.append(f"📝 Название: *{task['title']}*")
                        if old["status"]   != task["status"]:   changes.append(f"🔄 {STATUS_RU.get(old['status'])} → *{STATUS_RU.get(task['status'])}*")
                        if old["priority"] != task["priority"]: changes.append(f"⚡ Приоритет: {PRIO_RU.get(task['priority'])}")
                        if old["deadline"] != task["deadline"]: changes.append(f"📅 Дедлайн: *{task['deadline'] or 'убран'}*")
                        if old["assignee"] != task["assignee"]: changes.append(f"👤 Исполнитель: *{task['assignee'] or '—'}*")
                        if changes: await _notify("sheets_update", task, changes)
                    else:
                        await _notify("create", task)
                for tid in _last_state:
                    if tid not in current:
                        await _notify("delete", _last_state[tid])

            _last_state = current
        except Exception as e:
            logger.error(f"check_sheet_changes: {e}")

# ══════════════════════════════════════════════════════════
# DAILY REMINDERS
# ══════════════════════════════════════════════════════════
async def send_daily_reminders():
    while True:
        now   = datetime.now()
        next9 = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if now >= next9: next9 += timedelta(days=1)
        await asyncio.sleep((next9 - now).total_seconds())

        try:
            chat_id = _get_notify_chat_id()
            if not chat_id: continue

            tasks = get_all_tasks(); today = date.today()
            overdue  = [t for t in tasks if t["deadline"] and t["status"]!="done" and _safe_date(t["deadline"])<today]
            td_tasks = [t for t in tasks if t["deadline"] and t["status"]!="done" and _safe_date(t["deadline"])==today]
            upcoming = [t for t in tasks if t["deadline"] and t["status"]!="done"
                        and today < _safe_date(t["deadline"]) <= today+timedelta(days=3)]

            if not overdue and not td_tasks and not upcoming: continue

            lines = [f"☀️ *Доброе утро! {today.strftime('%d.%m.%Y')}*\n"]
            if overdue:
                lines.append(f"🔴 *Просрочено ({len(overdue)}):*")
                for t in overdue[:5]: lines.append(f"  • {t['title']} _{t['deadline']}_")
            if td_tasks:
                lines.append(f"\n📅 *Сегодня ({len(td_tasks)}):*")
                for t in td_tasks: lines.append(f"  • {t['title']}")
            if upcoming:
                lines.append(f"\n🟢 *Ближайшие ({len(upcoming)}):*")
                for t in upcoming[:3]: lines.append(f"  • {t['title']} _{t['deadline']}_")

            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Задачи",        callback_data="m:tasks"),
                 InlineKeyboardButton("🔴 Просроченные", callback_data="m:overdue")],
                [InlineKeyboardButton("🌐 Открыть приложение", url=WEBAPP_URL)],
            ])
            await bot.send_message(chat_id, "\n".join(lines), parse_mode="Markdown", reply_markup=kb)
        except Exception as e:
            logger.error(f"daily_reminders: {e}")

# ══════════════════════════════════════════════════════════
# STARTUP
# ══════════════════════════════════════════════════════════
@app.on_event("startup")
async def startup():
    # 1. Загружаем chat_ids из Sheets
    _load_chat_ids()

    # 2. Google Sheets
    try:
        s = get_sheet(); logger.info(f"✅ Sheets: {s.title}")
    except Exception as e:
        logger.error(f"❌ Sheets: {e}")

    # 3. Регистрируем webhook автоматически
    await setup_webhook()

    # 4. Фоновые задачи
    asyncio.create_task(check_sheet_changes())
    asyncio.create_task(send_daily_reminders())
    logger.info("✅ Запущен. MY_TELEGRAM_ID=%s, notify_chat_id=%s",
                MY_TELEGRAM_ID, _get_notify_chat_id())

@app.on_event("shutdown")
async def shutdown():
    await bot.close()

# ══════════════════════════════════════════════════════════
# WEBHOOK HANDLER
# ══════════════════════════════════════════════════════════
_tg_app = None

@app.post("/webhook/{token}")
async def telegram_webhook(token: str, request: Request):
    if token != BOT_TOKEN:
        raise HTTPException(status_code=403)
    global _tg_app
    if _tg_app is None:
        _tg_app = Application.builder().token(BOT_TOKEN).build()
        _tg_app.add_handler(CommandHandler("start",   cmd_start))
        _tg_app.add_handler(CommandHandler("menu",    cmd_start))
        _tg_app.add_handler(CommandHandler("tasks",   cmd_tasks))
        _tg_app.add_handler(CommandHandler("today",   cmd_today))
        _tg_app.add_handler(CommandHandler("overdue", cmd_overdue))
        _tg_app.add_handler(CommandHandler("add",     cmd_add))
        _tg_app.add_handler(CommandHandler("done",    cmd_done))
        _tg_app.add_handler(CommandHandler("stats",   cmd_stats))
        _tg_app.add_handler(CommandHandler("help",    cmd_help))
        _tg_app.add_handler(CallbackQueryHandler(handle_callback))
        await _tg_app.initialize()
    data   = await request.json()
    update = Update.de_json(data, bot)
    await _tg_app.process_update(update)
    return {"ok": True}

def _log(uid, uname, action, tid, title, changes):
    try:
        get_sheet(LOG_SHEET_NAME).append_row([
            datetime.now().isoformat(timespec="seconds"), uid, uname, action, tid, title, changes
        ])
    except Exception as e:
        logger.warning(f"log: {e}")

# ══ Serve frontend static files ════════════════════════════
# Всё в папке static/ доступно по URL /
# Это позволяет держать frontend и backend на одном Railway
import os as _os
_static = _os.path.join(_os.path.dirname(__file__), "static")
if _os.path.isdir(_static):
    app.mount("/", StaticFiles(directory=_static, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
