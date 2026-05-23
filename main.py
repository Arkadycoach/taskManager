"""
Task Manager Bot — полный бэкенд
FastAPI + python-telegram-bot + gspread + OpenAI Whisper + Claude AI
"""

import asyncio, json, logging, os, uuid, re
from datetime import datetime, timedelta, date
from typing import Optional

import gspread
import httpx
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from google.oauth2.service_account import Credentials
from pydantic import BaseModel
from telegram import (Bot, InlineKeyboardButton, InlineKeyboardMarkup,
                      Update, BotCommand)
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                           ContextTypes, MessageHandler, filters)

# ══════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════
BOT_TOKEN         = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
WEBAPP_URL        = os.getenv("WEBAPP_URL", "https://your-frontend-url.com")
SHEET_ID          = os.getenv("SHEET_ID",  "YOUR_GOOGLE_SHEET_ID")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON", "")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# ★ Твой Telegram user_id — уведомления будут приходить ТОЛЬКО тебе
# Узнать можно написав @userinfobot
MY_TELEGRAM_ID = int(os.getenv("MY_TELEGRAM_ID", "0"))

SHEET_NAME     = "Tasks"
LOG_SHEET_NAME = "ChangeLog"
SETTINGS_SHEET = "⚙️ Настройки"

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# ══════════════════════════════════════════════════════
# КОЛОНКИ И МАППИНГИ
# ══════════════════════════════════════════════════════
COLUMNS = [
    "ID", "Название", "Описание", "Статус", "Приоритет",
    "Дедлайн", "Исполнитель", "UserID", "Имя пользователя",
    "Создано", "Обновлено", "ID Календаря"
]

STATUS_TO_RU   = {"todo": "Новая",   "doing": "В работе", "done": "Готово"}
STATUS_FROM_RU = {"Новая": "todo",   "В работе": "doing", "Готово": "done"}
PRIO_TO_RU     = {"low": "Низкий",  "medium": "Средний", "high": "Высокий"}
PRIO_FROM_RU   = {"Низкий": "low",  "Средний": "medium", "Высокий": "high"}
STATUS_EMOJI   = {"todo": "🔵", "doing": "🟡", "done": "✅"}
PRIO_EMOJI     = {"high": "🔴", "medium": "🟡", "low": "🟢"}
TASKS_PER_PAGE = 5

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════
# GOOGLE SHEETS
# ══════════════════════════════════════════════════════
def get_sheets_client():
    d = json.loads(GOOGLE_CREDS_JSON) if GOOGLE_CREDS_JSON else json.load(open("service_account.json"))
    return gspread.authorize(Credentials.from_service_account_info(d, scopes=SCOPES))

def get_sheet(name=SHEET_NAME):
    sp = get_sheets_client().open_by_key(SHEET_ID)
    try:
        sheet = sp.worksheet(name)
        if name == SHEET_NAME: _ensure_headers(sheet, sp)
        return sheet
    except gspread.WorksheetNotFound:
        sheet = sp.add_worksheet(title=name, rows=1000, cols=len(COLUMNS))
        if name == SHEET_NAME:
            sheet.append_row(COLUMNS)
            _setup_validation(sp, sheet)
        elif name == LOG_SHEET_NAME:
            sheet.append_row(["Время","UserID","Пользователь","Действие","ID задачи","Название","Изменения"])
        return sheet

def _ensure_headers(sheet, sp):
    try:
        row = sheet.row_values(1)
        if row and len(row) > 1 and row[1] == "Title":
            sheet.update("A1", [COLUMNS])
        if row and len(row) < 12:
            _setup_validation(sp, sheet)
    except Exception as e:
        logger.warning(f"_ensure_headers: {e}")

def _setup_validation(sp, sheet):
    try:
        sid = sheet.id
        sp.batch_update({"requests": [
            {"updateSheetProperties": {
                "properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount"}},
            {"setDataValidation": {
                "range": {"sheetId": sid, "startRowIndex": 1, "endRowIndex": 1000, "startColumnIndex": 3, "endColumnIndex": 4},
                "rule": {"condition": {"type": "ONE_OF_LIST", "values": [
                    {"userEnteredValue": v} for v in ["Новая", "В работе", "Готово"]
                ]}, "showCustomUi": True, "strict": True}}},
            {"setDataValidation": {
                "range": {"sheetId": sid, "startRowIndex": 1, "endRowIndex": 1000, "startColumnIndex": 4, "endColumnIndex": 5},
                "rule": {"condition": {"type": "ONE_OF_LIST", "values": [
                    {"userEnteredValue": v} for v in ["Высокий", "Средний", "Низкий"]
                ]}, "showCustomUi": True, "strict": True}}},
        ]})
    except Exception as e:
        logger.error(f"_setup_validation: {e}")

def row_to_task(row: list) -> dict:
    def g(i): return row[i] if i < len(row) else ""
    raw_s = g(3); raw_p = g(4)
    return {
        "id": g(0), "title": g(1), "description": g(2),
        "status":   STATUS_FROM_RU.get(raw_s) or (raw_s if raw_s in STATUS_TO_RU else "todo"),
        "priority": PRIO_FROM_RU.get(raw_p)   or (raw_p if raw_p in PRIO_TO_RU   else "medium"),
        "deadline": g(5), "assignee": g(6),
        "user_id": g(7), "user_name": g(8),
        "created_at": g(9), "updated_at": g(10),
    }

def get_all_tasks() -> list:
    sheet = get_sheet()
    rows  = sheet.get_all_values()
    return [row_to_task(r) for r in rows[1:] if r and r[0] and len(r) > 1]

# ══════════════════════════════════════════════════════
# MODELS
# ══════════════════════════════════════════════════════
class TaskCreate(BaseModel):
    title: str; description: str = ""; status: str = "todo"
    priority: str = "medium"; deadline: str = ""; assignee: str = ""
    user_id: str = ""; user_name: str = ""

class TaskUpdate(BaseModel):
    title: Optional[str] = None; description: Optional[str] = None
    status: Optional[str] = None; priority: Optional[str] = None
    deadline: Optional[str] = None; assignee: Optional[str] = None
    user_id: str = ""; user_name: str = ""

# ══════════════════════════════════════════════════════
# FASTAPI
# ══════════════════════════════════════════════════════
app = FastAPI(title="Task Manager API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
bot = Bot(token=BOT_TOKEN)

# user_id → chat_id  (заполняется при /start)
user_registry: dict[str, int] = {}

def _get_my_chat_id() -> Optional[int]:
    """Возвращает chat_id владельца бота (MY_TELEGRAM_ID)."""
    if MY_TELEGRAM_ID and str(MY_TELEGRAM_ID) in user_registry:
        return user_registry[str(MY_TELEGRAM_ID)]
    # Если только один пользователь — берём его
    if len(user_registry) == 1:
        return list(user_registry.values())[0]
    return None

@app.get("/tasks")
async def get_tasks(user_id: str = ""):
    try:
        tasks = get_all_tasks()
        return {"tasks": tasks}
    except Exception as e:
        logger.error(f"get_tasks: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/tasks")
async def create_task(task: TaskCreate, x_user_id: str = Header(default="")):
    try:
        sheet = get_sheet()
        tid = str(uuid.uuid4())[:8].upper()
        now = datetime.now().isoformat(timespec="seconds")
        uid = task.user_id or x_user_id
        row = [tid, task.title, task.description,
               STATUS_TO_RU.get(task.status, task.status),
               PRIO_TO_RU.get(task.priority, task.priority),
               task.deadline, task.assignee, uid, task.user_name, now, now, ""]
        sheet.append_row(row)
        new_task = {"id": tid, "title": task.title, "description": task.description,
                    "status": task.status, "priority": task.priority,
                    "deadline": task.deadline, "assignee": task.assignee,
                    "user_id": uid, "user_name": task.user_name, "created_at": now, "updated_at": now}
        _log(uid, task.user_name, "СОЗДАНИЕ", tid, task.title, f"Создана")
        await _notify("create", new_task)
        return {"task": new_task}
    except Exception as e:
        logger.error(f"create_task: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/tasks/{task_id}")
async def update_task(task_id: str, upd: TaskUpdate, x_user_id: str = Header(default="")):
    try:
        sheet = get_sheet()
        rows  = sheet.get_all_values()
        row_idx = None; old = None
        for i, row in enumerate(rows[1:], start=2):
            if row and row[0] == task_id:
                row_idx = i; old = row_to_task(row); break
        if not row_idx:
            raise HTTPException(status_code=404, detail="Not found")

        changes = []
        sl = STATUS_TO_RU; pl = PRIO_TO_RU
        if upd.title       is not None: sheet.update_cell(row_idx,2,upd.title);              old["title"]!=upd.title and changes.append(f"название → {upd.title}")
        if upd.description is not None: sheet.update_cell(row_idx,3,upd.description)
        if upd.status      is not None: sheet.update_cell(row_idx,4,sl.get(upd.status,upd.status)); old["status"]!=upd.status and changes.append(f"статус: {sl.get(old['status'])} → {sl.get(upd.status)}")
        if upd.priority    is not None: sheet.update_cell(row_idx,5,pl.get(upd.priority,upd.priority)); old["priority"]!=upd.priority and changes.append(f"приоритет: {pl.get(upd.priority)}")
        if upd.deadline    is not None: sheet.update_cell(row_idx,6,upd.deadline);           old["deadline"]!=upd.deadline and changes.append(f"дедлайн: {upd.deadline or 'убран'}")
        if upd.assignee    is not None: sheet.update_cell(row_idx,7,upd.assignee);           old["assignee"]!=upd.assignee and changes.append(f"исполнитель: {upd.assignee or '—'}")
        sheet.update_cell(row_idx, 11, datetime.now().isoformat(timespec="seconds"))

        updated = {**old, **{k:v for k,v in {"title":upd.title,"status":upd.status,"priority":upd.priority,
                                               "deadline":upd.deadline,"assignee":upd.assignee}.items() if v is not None}}
        uid = upd.user_id or x_user_id
        if changes:
            _log(uid, upd.user_name, "ОБНОВЛЕНИЕ", task_id, upd.title or old["title"], "; ".join(changes))
            await _notify("update", updated, changes)
        if upd.status == "done" and old["status"] != "done":
            await _notify("done", updated)
        return {"success": True}
    except HTTPException: raise
    except Exception as e:
        logger.error(f"update_task: {e}"); raise HTTPException(status_code=500, detail=str(e))

@app.delete("/tasks/{task_id}")
async def delete_task(task_id: str, x_user_id: str = Header(default="")):
    try:
        sheet = get_sheet()
        rows  = sheet.get_all_values()
        for i, row in enumerate(rows[1:], start=2):
            if row and row[0] == task_id:
                t = row_to_task(row)
                sheet.delete_rows(i)
                _log(x_user_id, "", "УДАЛЕНИЕ", task_id, row[1] if len(row)>1 else "", "Удалена")
                await _notify("delete", t)
                return {"success": True}
        raise HTTPException(status_code=404, detail="Not found")
    except HTTPException: raise
    except Exception as e:
        logger.error(f"delete_task: {e}"); raise HTTPException(status_code=500, detail=str(e))

@app.post("/register")
async def register_user(data: dict):
    uid = str(data.get("user_id", ""))
    cid = data.get("chat_id")
    if uid and cid: user_registry[uid] = int(cid)
    return {"ok": True}

@app.post("/admin/setup-sheet")
async def admin_setup_sheet():
    try:
        sp = get_sheets_client().open_by_key(SHEET_ID)
        s  = sp.worksheet(SHEET_NAME)
        s.update("A1", [COLUMNS]); _setup_validation(sp, s)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    return {"status": "ok", "time": datetime.now().isoformat()}

# ══════════════════════════════════════════════════════
# УВЕДОМЛЕНИЯ
# Куда: ТОЛЬКО владельцу бота (MY_TELEGRAM_ID)
# Когда:
#   create       — задача создана (в приложении или Sheets)
#   update       — задача изменена
#   done         — задача выполнена 🎉
#   delete       — задача удалена
#   sheets_update — изменение напрямую в Sheets
#   reminder     — утреннее напоминание
# ══════════════════════════════════════════════════════
async def _notify(event: str, task: dict, changes: list = None):
    chat_id = _get_my_chat_id()
    if not chat_id:
        logger.info(f"notify skipped — no chat_id registered. Send /start to bot first.")
        return

    se = STATUS_EMOJI.get(task.get("status","todo"), "🔵")
    pe = PRIO_EMOJI.get(task.get("priority","medium"), "🟡")
    title  = task.get("title", "")
    dl     = task.get("deadline", "")
    asgn   = task.get("assignee", "")
    tid    = task.get("id", "")

    dl_str   = f"\n📅 *Дедлайн:* {dl}" if dl else ""
    asgn_str = f"\n👤 *Исполнитель:* {asgn}" if asgn else ""

    if event == "create":
        text = (f"✅ *Задача создана*\n\n"
                f"{pe} *{title}*\n"
                f"{se} {STATUS_TO_RU.get(task.get('status','todo'))}{dl_str}{asgn_str}")
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
            [InlineKeyboardButton("📋 Открыть приложение", url=WEBAPP_URL)],
        ])
    elif event == "done":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📋 Все задачи", callback_data="m:tasks:0:all")]])

    try:
        await bot.send_message(chat_id=chat_id, text=text,
                               parse_mode="Markdown", reply_markup=kb)
    except Exception as e:
        logger.error(f"_notify: {e}")

# ══════════════════════════════════════════════════════
# BOT MENU — ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ══════════════════════════════════════════════════════
def _main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Все задачи",      callback_data="m:tasks:0:all"),
         InlineKeyboardButton("📅 Сегодня",         callback_data="m:tasks:0:today")],
        [InlineKeyboardButton("🔴 Просроченные",    callback_data="m:tasks:0:overdue"),
         InlineKeyboardButton("🟡 В работе",        callback_data="m:tasks:0:doing")],
        [InlineKeyboardButton("✅ Выполненные",     callback_data="m:tasks:0:done"),
         InlineKeyboardButton("📊 Статистика",      callback_data="m:stats")],
        [InlineKeyboardButton("🌐 Открыть приложение", url=WEBAPP_URL)],
    ])

def _tasks_for_filter(tasks: list, f: str) -> list:
    today = date.today()
    if f == "all":     return [t for t in tasks if t["status"] != "done"]
    if f == "doing":   return [t for t in tasks if t["status"] == "doing"]
    if f == "done":    return [t for t in tasks if t["status"] == "done"]
    if f == "today":
        return [t for t in tasks if t["deadline"] and t["status"] != "done"
                and date.fromisoformat(t["deadline"]) == today]
    if f == "overdue":
        return [t for t in tasks if t["deadline"] and t["status"] != "done"
                and _safe_date(t["deadline"]) < today]
    return tasks

def _safe_date(s: str):
    try: return date.fromisoformat(s)
    except: return date(9999,1,1)

FILTER_LABELS = {
    "all": "📋 Активные задачи", "doing": "🟡 В работе",
    "done": "✅ Выполненные", "today": "📅 Дедлайн сегодня",
    "overdue": "🔴 Просроченные",
}

async def _send_task_list(target, page: int, f: str, edit=False):
    """Отправляет или редактирует сообщение со списком задач."""
    tasks  = get_all_tasks()
    subset = _tasks_for_filter(tasks, f)
    total  = len(subset)
    pages  = max(1, (total + TASKS_PER_PAGE - 1) // TASKS_PER_PAGE)
    page   = max(0, min(page, pages - 1))
    chunk  = subset[page * TASKS_PER_PAGE : (page + 1) * TASKS_PER_PAGE]

    header = f"{FILTER_LABELS.get(f,'Задачи')} ({total})\n{'─'*28}\n\n"
    if not chunk:
        body = "_Задач нет_ 🎉"
    else:
        lines = []
        for i, t in enumerate(chunk, start=page * TASKS_PER_PAGE + 1):
            se   = STATUS_EMOJI.get(t["status"], "•")
            pe   = PRIO_EMOJI.get(t["priority"], "")
            dl   = f"  📅 {t['deadline']}" if t["deadline"] else ""
            asgn = f"  👤 {t['assignee']}" if t["assignee"] else ""
            lines.append(f"{i}. {pe}{se} *{t['title']}*{dl}{asgn}")
        body = "\n".join(lines)

    text = header + body

    # Кнопки для каждой задачи на странице
    rows = []
    for t in chunk:
        rows.append([InlineKeyboardButton(
            f"👁 {t['title'][:28]}",
            callback_data=f"m:task:{t['id']}"
        )])

    # Пагинация
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("← Назад", callback_data=f"m:tasks:{page-1}:{f}"))
    nav.append(InlineKeyboardButton(f"{page+1}/{pages}", callback_data="noop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton("Вперёд →", callback_data=f"m:tasks:{page+1}:{f}"))
    if nav: rows.append(nav)

    rows.append([InlineKeyboardButton("🏠 Главное меню", callback_data="m:main")])
    kb = InlineKeyboardMarkup(rows)

    if edit:
        await target.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
    else:
        await target.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)

async def _send_task_detail(query, task_id: str, back_filter="all", back_page=0):
    """Показывает детальную карточку задачи с кнопками действий."""
    tasks = get_all_tasks()
    task  = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        await query.edit_message_text("❌ Задача не найдена.")
        return

    se   = STATUS_EMOJI.get(task["status"], "•")
    pe   = PRIO_EMOJI.get(task["priority"], "•")
    dl   = task.get("deadline","")
    asgn = task.get("assignee","")
    desc = task.get("description","")

    # Проверяем просрочена ли
    overdue_mark = ""
    if dl and task["status"] != "done":
        try:
            if date.fromisoformat(dl) < date.today(): overdue_mark = " ⚠️ ПРОСРОЧЕНА"
        except: pass

    text = (
        f"📋 *{task['title']}*{overdue_mark}\n"
        f"{'─'*30}\n"
        f"{se} *Статус:* {STATUS_TO_RU.get(task['status'])}\n"
        f"{pe} *Приоритет:* {PRIO_TO_RU.get(task['priority'])}\n"
    )
    if dl:   text += f"📅 *Дедлайн:* {dl}\n"
    if asgn: text += f"👤 *Исполнитель:* {asgn}\n"
    if desc: text += f"\n📝 _{desc}_\n"
    text += f"\n🆔 `{task['id']}`"

    # Кнопки действий
    status_btns = []
    if task["status"] != "todo":
        status_btns.append(InlineKeyboardButton("🔵 Новая",    callback_data=f"s:todo:{task_id}"))
    if task["status"] != "doing":
        status_btns.append(InlineKeyboardButton("▶️ В работу", callback_data=f"s:doing:{task_id}"))
    if task["status"] != "done":
        status_btns.append(InlineKeyboardButton("✅ Готово",   callback_data=f"s:done:{task_id}"))

    rows = []
    if status_btns: rows.append(status_btns)
    rows.append([InlineKeyboardButton("🗑 Удалить", callback_data=f"del:{task_id}:{back_filter}:{back_page}")])
    rows.append([InlineKeyboardButton(f"← К списку", callback_data=f"m:tasks:{back_page}:{back_filter}"),
                 InlineKeyboardButton("🏠 Меню",     callback_data="m:main")])

    await query.edit_message_text(text, parse_mode="Markdown",
                                  reply_markup=InlineKeyboardMarkup(rows))

async def _send_main_menu(target, edit=False):
    tasks    = get_all_tasks()
    today    = date.today()
    total    = len(tasks)
    active   = sum(1 for t in tasks if t["status"] != "done")
    doing    = sum(1 for t in tasks if t["status"] == "doing")
    done     = sum(1 for t in tasks if t["status"] == "done")
    overdue  = sum(1 for t in tasks if t["deadline"] and t["status"]!="done" and _safe_date(t["deadline"])<today)
    td_count = sum(1 for t in tasks if t["deadline"] and t["status"]!="done" and _safe_date(t["deadline"])==today)
    pct      = round(done/total*100) if total else 0

    bar_len  = 10
    filled   = round(pct / 100 * bar_len)
    bar      = "█" * filled + "░" * (bar_len - filled)

    text = (
        f"🏠 *Главное меню*\n"
        f"{'─'*28}\n"
        f"[{bar}] *{pct}%*\n\n"
        f"📋 Всего задач: *{total}*\n"
        f"🔵 Новых: *{active - doing}*   🟡 В работе: *{doing}*   ✅ Готово: *{done}*\n"
    )
    if overdue:  text += f"🔴 Просрочено: *{overdue}*\n"
    if td_count: text += f"📅 Дедлайн сегодня: *{td_count}*\n"

    if edit:
        await target.edit_message_text(text, parse_mode="Markdown", reply_markup=_main_menu_kb())
    else:
        await target.message.reply_text(text, parse_mode="Markdown", reply_markup=_main_menu_kb())

async def _send_stats(query):
    tasks   = get_all_tasks()
    today   = date.today()
    total   = len(tasks)
    by_s    = {"todo":0,"doing":0,"done":0}
    overdue = 0
    for t in tasks:
        by_s[t["status"]] = by_s.get(t["status"],0)+1
        if t["deadline"] and t["status"]!="done" and _safe_date(t["deadline"])<today: overdue+=1
    pct = round(by_s["done"]/total*100) if total else 0

    today_str = date.today().isoformat()
    done_today = sum(1 for t in tasks if t["status"]=="done" and (t.get("updated_at","") or "").startswith(today_str))

    text = (
        f"📊 *Статистика задач*\n"
        f"{'─'*28}\n\n"
        f"📋 Всего: *{total}*\n"
        f"├ 🔵 Новые: {by_s['todo']}\n"
        f"├ 🟡 В работе: {by_s['doing']}\n"
        f"└ ✅ Готово: {by_s['done']}\n\n"
        f"🔴 Просрочено: *{overdue}*\n"
        f"🎯 Выполнено сегодня: *{done_today}*\n"
        f"📈 Прогресс: *{pct}%*"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Главное меню", callback_data="m:main")]])
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)

# ══════════════════════════════════════════════════════
# TELEGRAM COMMAND HANDLERS
# ══════════════════════════════════════════════════════
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid  = str(user.id)
    user_registry[uid] = update.effective_chat.id

    await bot.set_my_commands([
        BotCommand("start",  "🏠 Главное меню"),
        BotCommand("tasks",  "📋 Все задачи"),
        BotCommand("today",  "📅 Дедлайны сегодня"),
        BotCommand("add",    "➕ Добавить задачу"),
        BotCommand("done",   "✅ Выполнить задачу"),
        BotCommand("stats",  "📊 Статистика"),
        BotCommand("help",   "❓ Помощь"),
    ])
    await _send_main_menu(update)

async def cmd_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    user_registry[uid] = update.effective_chat.id
    await _send_task_list(update, 0, "all")

async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    user_registry[uid] = update.effective_chat.id
    await _send_task_list(update, 0, "today")

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks   = get_all_tasks()
    today   = date.today()
    total   = len(tasks)
    by_s    = {"todo":0,"doing":0,"done":0}
    overdue = 0
    for t in tasks:
        by_s[t["status"]] = by_s.get(t["status"],0)+1
        if t["deadline"] and t["status"]!="done" and _safe_date(t["deadline"])<today: overdue+=1
    pct = round(by_s["done"]/total*100) if total else 0
    text = (f"📊 *Статистика*\n\nВсего: *{total}*\n"
            f"├ 🔵 Новые: {by_s['todo']}\n├ 🟡 В работе: {by_s['doing']}\n└ ✅ Готово: {by_s['done']}\n\n"
            f"🔴 Просрочено: *{overdue}*\n📈 Прогресс: *{pct}%*")
    await update.message.reply_text(text, parse_mode="Markdown",
                                    reply_markup=_main_menu_kb())

async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid   = str(update.effective_user.id)
    uname = update.effective_user.username or update.effective_user.first_name
    user_registry[uid] = update.effective_chat.id
    if not context.args:
        await update.message.reply_text(
            "➕ *Добавить задачу:*\n\n"
            "`/add Название !приоритет @исполнитель 2025-06-15`\n\n"
            "*Приоритет:* `!высокий` `!средний` `!низкий`\n\n"
            "*Примеры:*\n"
            "`/add Написать отчёт !высокий`\n"
            "`/add Встреча с Иваном @ivan 2025-06-10`",
            parse_mode="Markdown"); return

    raw = " ".join(context.args)
    priority="medium"; assignee=""; deadline=""
    for key, val in {"!высокий":"high","!срочно":"high","!средний":"medium","!низкий":"low"}.items():
        if key in raw.lower(): priority=val; raw=re.sub(re.escape(key),"",raw,flags=re.IGNORECASE)
    m = re.search(r"@(\S+)", raw)
    if m: assignee=m.group(1); raw=raw.replace(m.group(0),"")
    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", raw)
    if m: deadline=m.group(1); raw=raw.replace(m.group(0),"")
    title = raw.strip()
    if not title: await update.message.reply_text("❌ Введи название задачи."); return

    sheet = get_sheet()
    tid   = str(uuid.uuid4())[:8].upper()
    now   = datetime.now().isoformat(timespec="seconds")
    sheet.append_row([tid,title,"",STATUS_TO_RU["todo"],PRIO_TO_RU[priority],
                      deadline,assignee,uid,uname,now,now,""])
    task = {"id":tid,"title":title,"status":"todo","priority":priority,
            "deadline":deadline,"assignee":assignee}
    await _notify("create", task)
    pe  = PRIO_EMOJI[priority]
    dl  = f"\n📅 {deadline}" if deadline else ""
    asn = f"\n👤 @{assignee}" if assignee else ""
    kb  = InlineKeyboardMarkup([[
        InlineKeyboardButton("▶️ В работу", callback_data=f"s:doing:{tid}"),
        InlineKeyboardButton("📋 Меню",     callback_data="m:main"),
    ]])
    await update.message.reply_text(
        f"✅ *Задача добавлена!*\n\n{pe} *{title}*{dl}{asn}\n\n🆔 `{tid}`",
        parse_mode="Markdown", reply_markup=kb)

async def cmd_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    user_registry[uid] = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("Формат: `/done ID_или_название`", parse_mode="Markdown"); return
    query = " ".join(context.args).strip()
    sheet = get_sheet()
    rows  = sheet.get_all_values()
    for i, row in enumerate(rows[1:], start=2):
        if not row or not row[0]: continue
        if row[0].upper()==query.upper() or (row[1] and query.lower() in row[1].lower()):
            task = row_to_task(row)
            sheet.update_cell(i,4,"Готово")
            sheet.update_cell(i,11,datetime.now().isoformat(timespec="seconds"))
            await _notify("done", task)
            await update.message.reply_text(f"🎉 *Выполнено!*\n\n✅ {task['title']}",
                                            parse_mode="Markdown", reply_markup=_main_menu_kb())
            return
    await update.message.reply_text(f"❌ Задача «{query}» не найдена.\n\nПопробуй /tasks")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "❓ *Task Manager — справка*\n\n"
        "*Команды:*\n"
        "/start — 🏠 Главное меню\n"
        "/tasks — 📋 Список задач с кнопками\n"
        "/today — 📅 Дедлайны сегодня\n"
        "/add Название \\!приоритет @кто дата — ➕ Добавить\n"
        "/done ID — ✅ Выполнить задачу\n"
        "/stats — 📊 Статистика\n\n"
        "*Голосовой ассистент:*\n"
        "Просто отправь голосовое\\!\n\n"
        "• «Создай задачу встреча, высокий приоритет»\n"
        "• «Отметь задачу отчёт как выполненную»\n"
        "• «Покажи мои задачи»\n"
        "• «Статистика»\n\n"
        "*Уведомления приходят когда:*\n"
        "• Создана новая задача\n"
        "• Задача изменена\n"
        "• Задача выполнена 🎉\n"
        "• Изменение прямо в Google Sheets\n"
        "• Утренний дайджест в 9:00"
    )
    await update.message.reply_text(text, parse_mode="MarkdownV2",
                                    reply_markup=_main_menu_kb())

# ══════════════════════════════════════════════════════
# CALLBACK ROUTER
# Формат callback_data:
#   m:main              — главное меню
#   m:tasks:PAGE:FILTER — список задач
#   m:task:ID           — детали задачи
#   m:stats             — статистика
#   s:STATUS:ID         — сменить статус
#   del:ID:FILTER:PAGE  — удалить задачу
#   noop                — ничего не делать
# ══════════════════════════════════════════════════════
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""

    try:
        if data == "noop":
            return

        elif data == "m:main":
            await _send_main_menu(query, edit=True)

        elif data == "m:stats":
            await _send_stats(query)

        elif data.startswith("m:tasks:"):
            # m:tasks:PAGE:FILTER
            parts = data.split(":")
            page  = int(parts[2]) if len(parts)>2 else 0
            filt  = parts[3]       if len(parts)>3 else "all"
            await _send_task_list(query, page, filt, edit=True)

        elif data.startswith("m:task:"):
            # m:task:TASKID  — детали задачи
            tid = data.split(":")[2]
            await _send_task_detail(query, tid)

        elif data.startswith("s:"):
            # s:STATUS:TASKID
            parts      = data.split(":")
            new_status = parts[1]
            tid        = parts[2]
            sheet = get_sheet()
            rows  = sheet.get_all_values()
            for i, row in enumerate(rows[1:], start=2):
                if row and row[0] == tid:
                    task = row_to_task(row)
                    sheet.update_cell(i,4,STATUS_TO_RU.get(new_status,new_status))
                    sheet.update_cell(i,11,datetime.now().isoformat(timespec="seconds"))
                    task["status"] = new_status
                    if new_status == "done":
                        await _notify("done", task)
                        await query.edit_message_text(
                            f"🎉 *Выполнено!*\n\n✅ *{task['title']}*",
                            parse_mode="Markdown",
                            reply_markup=InlineKeyboardMarkup([[
                                InlineKeyboardButton("📋 Все задачи", callback_data="m:tasks:0:all"),
                                InlineKeyboardButton("🏠 Меню",       callback_data="m:main"),
                            ]]))
                    else:
                        await _send_task_detail(query, tid)
                    return
            await query.edit_message_text("❌ Задача не найдена.")

        elif data.startswith("del:"):
            # del:TASKID:FILTER:PAGE
            parts = data.split(":")
            tid   = parts[1]
            filt  = parts[2] if len(parts)>2 else "all"
            pg    = int(parts[3]) if len(parts)>3 else 0
            sheet = get_sheet()
            rows  = sheet.get_all_values()
            for i, row in enumerate(rows[1:], start=2):
                if row and row[0] == tid:
                    task = row_to_task(row)
                    sheet.delete_rows(i)
                    await _notify("delete", task)
                    await _send_task_list(query, pg, filt, edit=True)
                    return
            await query.edit_message_text("❌ Задача не найдена.")

    except Exception as e:
        logger.error(f"callback '{data}': {e}")
        try:
            await query.edit_message_text(f"❌ Ошибка: {str(e)[:200]}")
        except: pass

# ══════════════════════════════════════════════════════
# ГОЛОСОВОЙ АССИСТЕНТ
# ══════════════════════════════════════════════════════
async def transcribe_voice(voice_bytes: bytes) -> str:
    if not OPENAI_API_KEY: return ""
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                files={"file": ("voice.ogg", voice_bytes, "audio/ogg")},
                data={"model": "whisper-1", "language": "ru"},
            )
            r.raise_for_status()
            return r.json().get("text","")
    except Exception as e:
        logger.error(f"transcribe: {e}"); return ""

async def parse_voice_command(text: str, tasks_summary: str) -> dict:
    if not ANTHROPIC_API_KEY: return {"action":"unknown","raw":text}
    prompt = f"""Ты — AI-ассистент таск-менеджера. Верни ТОЛЬКО валидный JSON без markdown.

Actions: create_task | update_task | complete_task | delete_task | list_tasks | get_stats | unknown

create_task:    {{"action":"create_task","title":"...","description":"...","priority":"high|medium|low","deadline":"YYYY-MM-DD или пусто","assignee":"..."}}
update_task:    {{"action":"update_task","search_title":"...","updates":{{"status":"todo|doing|done","priority":"...","deadline":"...","assignee":"..."}}}}
complete_task:  {{"action":"complete_task","search_title":"..."}}
delete_task:    {{"action":"delete_task","search_title":"..."}}
list_tasks:     {{"action":"list_tasks"}}
get_stats:      {{"action":"get_stats"}}

Даты: "завтра"=+1д, "через неделю"=+7д, "пятница"=ближайшая пятница. Сегодня: {date.today().isoformat()}

Команда: {text}
Текущие задачи:
{tasks_summary}"""
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": ANTHROPIC_API_KEY,
                         "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": "claude-haiku-4-5-20251001", "max_tokens": 400,
                      "messages": [{"role":"user","content":prompt}]},
            )
            r.raise_for_status()
            content = r.json()["content"][0]["text"].strip()
            return json.loads(re.sub(r"```json\s*|\s*```","",content).strip())
    except Exception as e:
        logger.error(f"parse_voice: {e}"); return {"action":"unknown","raw":text}

async def execute_voice_action(action_data: dict, uid: str, uname: str) -> tuple[str, Optional[InlineKeyboardMarkup]]:
    action = action_data.get("action","unknown")
    kb_main = InlineKeyboardMarkup([[InlineKeyboardButton("📋 Все задачи", callback_data="m:tasks:0:all"),
                                     InlineKeyboardButton("🏠 Меню",       callback_data="m:main")]])
    if action == "create_task":
        title = action_data.get("title","Новая задача")
        prio  = action_data.get("priority","medium")
        dl    = action_data.get("deadline","")
        asgn  = action_data.get("assignee","")
        desc  = action_data.get("description","")
        sheet = get_sheet()
        tid   = str(uuid.uuid4())[:8].upper()
        now   = datetime.now().isoformat(timespec="seconds")
        sheet.append_row([tid,title,desc,STATUS_TO_RU["todo"],PRIO_TO_RU.get(prio,prio),
                          dl,asgn,uid,uname,now,now,""])
        task = {"id":tid,"title":title,"status":"todo","priority":prio,"deadline":dl,"assignee":asgn}
        await _notify("create", task)
        pe = PRIO_EMOJI.get(prio,"🟡")
        return (f"✅ *Создана!*\n\n{pe} *{title}*"
                + (f"\n📅 {dl}" if dl else "")
                + (f"\n👤 @{asgn}" if asgn else "")
                + f"\n🆔 `{tid}`", kb_main)

    elif action in ("complete_task","update_task","delete_task"):
        search = action_data.get("search_title","")
        sheet  = get_sheet()
        rows   = sheet.get_all_values()
        idx=None; found=None
        for i, row in enumerate(rows[1:],start=2):
            if row and row[1] and search.lower() in row[1].lower():
                idx=i; found=row_to_task(row); break
        if not found:
            return (f"❌ Задача «{search}» не найдена.", kb_main)

        if action == "complete_task":
            sheet.update_cell(idx,4,"Готово")
            sheet.update_cell(idx,11,datetime.now().isoformat(timespec="seconds"))
            found["status"]="done"
            await _notify("done", found)
            return (f"🎉 *Выполнено!*\n\n✅ {found['title']}", kb_main)

        elif action == "delete_task":
            sheet.delete_rows(idx)
            await _notify("delete", found)
            return (f"🗑 Удалено: ~~{found['title']}~~", kb_main)

        elif action == "update_task":
            updates = action_data.get("updates",{})
            changes = []
            if "status"   in updates: sheet.update_cell(idx,4,STATUS_TO_RU.get(updates["status"],updates["status"])); changes.append(f"статус → {STATUS_TO_RU.get(updates['status'])}")
            if "priority" in updates: sheet.update_cell(idx,5,PRIO_TO_RU.get(updates["priority"],updates["priority"])); changes.append(f"приоритет → {PRIO_TO_RU.get(updates['priority'])}")
            if "deadline" in updates: sheet.update_cell(idx,6,updates["deadline"]); changes.append(f"дедлайн → {updates['deadline']}")
            if "assignee" in updates: sheet.update_cell(idx,7,updates["assignee"]); changes.append(f"исполнитель → {updates['assignee']}")
            sheet.update_cell(idx,11,datetime.now().isoformat(timespec="seconds"))
            ch = "\n  • ".join(changes)
            return (f"✏️ *Обновлено*\n\n*{found['title']}*\n\n  • {ch}", kb_main)

    elif action == "list_tasks":
        tasks  = get_all_tasks()
        active = [t for t in tasks if t["status"]!="done"]
        if not active: return ("✅ Нет активных задач!", kb_main)
        lines = [f"📋 *Активные ({len(active)}):*\n"]
        for t in active[:8]:
            pe = PRIO_EMOJI.get(t["priority"],"")
            dl = f" _({t['deadline']})_" if t["deadline"] else ""
            lines.append(f"{STATUS_EMOJI.get(t['status'])}{pe} {t['title']}{dl}")
        return ("\n".join(lines), InlineKeyboardMarkup([[
            InlineKeyboardButton("📋 Открыть список", callback_data="m:tasks:0:all"),
            InlineKeyboardButton("🏠 Меню", callback_data="m:main")]]))

    elif action == "get_stats":
        text = await _format_stats_text()
        return (text, kb_main)

    return ("🤔 Не понял команду. Попробуй:\n"
            "• «Создай задачу встреча с клиентом»\n"
            "• «Отметь задачу отчёт как выполненную»\n"
            "• «Покажи мои задачи»", None)

async def _format_stats_text() -> str:
    tasks = get_all_tasks(); today=date.today(); total=len(tasks)
    by_s={"todo":0,"doing":0,"done":0}; overdue=0
    for t in tasks:
        by_s[t["status"]]=by_s.get(t["status"],0)+1
        if t["deadline"] and t["status"]!="done" and _safe_date(t["deadline"])<today: overdue+=1
    pct=round(by_s["done"]/total*100) if total else 0
    return (f"📊 *Статистика*\n\nВсего: *{total}*\n"
            f"├ 🔵 Новые: {by_s['todo']}\n├ 🟡 В работе: {by_s['doing']}\n└ ✅ Готово: {by_s['done']}\n\n"
            f"🔴 Просрочено: *{overdue}*\n📈 Прогресс: *{pct}%*")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid   = str(update.effective_user.id)
    uname = update.effective_user.username or update.effective_user.first_name
    user_registry[uid] = update.effective_chat.id
    if not OPENAI_API_KEY:
        await update.message.reply_text("❌ Голосовой ассистент не настроен.\nДобавь `OPENAI_API_KEY`."); return
    await update.message.reply_chat_action("typing")
    msg = await update.message.reply_text("🎙️ _Слушаю..._", parse_mode="Markdown")
    try:
        vf    = await update.message.voice.get_file()
        vb    = await vf.download_as_bytearray()
        await msg.edit_text("🎙️ _Распознаю речь..._", parse_mode="Markdown")
        transcript = await transcribe_voice(bytes(vb))
        if not transcript:
            await msg.edit_text("❌ Не удалось распознать. Попробуй ещё раз."); return
        await msg.edit_text(f"🎙️ _«{transcript}»_\n⚙️ _Выполняю..._", parse_mode="Markdown")
        tasks = get_all_tasks()
        summary = "\n".join(f"- [{t['id']}] {t['title']}" for t in tasks[:15] if t["status"]!="done")
        action_data = await parse_voice_command(transcript, summary)
        result, kb  = await execute_voice_action(action_data, uid, uname)
        await msg.edit_text(result, parse_mode="Markdown", reply_markup=kb)
    except Exception as e:
        logger.error(f"handle_voice: {e}")
        await msg.edit_text(f"❌ Ошибка: {str(e)[:200]}")

# ══════════════════════════════════════════════════════
# SHEETS POLLING — синхронизация изменений из Sheets
# ══════════════════════════════════════════════════════
_last_state: dict[str, dict] = {}

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
                        old = _last_state[tid]; changes=[]
                        if old["title"]    != task["title"]:    changes.append(f"📝 Название: *{task['title']}*")
                        if old["status"]   != task["status"]:   changes.append(f"🔄 {STATUS_TO_RU.get(old['status'])} → *{STATUS_TO_RU.get(task['status'])}*")
                        if old["priority"] != task["priority"]: changes.append(f"⚡ Приоритет: {PRIO_TO_RU.get(task['priority'])}")
                        if old["deadline"] != task["deadline"]: changes.append(f"📅 Дедлайн: *{task['deadline'] or 'убран'}*")
                        if old["assignee"] != task["assignee"]: changes.append(f"👤 Исполнитель: *{task['assignee'] or '—'}*")
                        if changes: await _notify("sheets_update", task, changes)
                    else:
                        await _notify("create", task)
                for tid in _last_state:
                    if tid not in current:
                        await _notify("delete", _last_state[tid])

            # Авто-генерация ID для строк добавленных вручную в Sheets
            sheet = get_sheet()
            rows  = sheet.get_all_values()
            now   = datetime.now().isoformat(timespec="seconds")
            for i, row in enumerate(rows[1:], start=2):
                if (not row[0].strip()) and len(row)>1 and row[1].strip():
                    new_id = str(uuid.uuid4())[:8].upper()
                    sheet.update_cell(i,1,new_id)
                    if not (row[9].strip() if len(row)>9 else ""): sheet.update_cell(i,10,now)
                    if not (row[10].strip() if len(row)>10 else ""): sheet.update_cell(i,11,now)

            _last_state = current
        except Exception as e:
            logger.error(f"check_sheet_changes: {e}")

# ══════════════════════════════════════════════════════
# УТРЕННИЕ НАПОМИНАНИЯ
# ══════════════════════════════════════════════════════
async def send_daily_reminders():
    while True:
        now  = datetime.now()
        next9 = now.replace(hour=9,minute=0,second=0,microsecond=0)
        if now >= next9: next9 += timedelta(days=1)
        await asyncio.sleep((next9 - now).total_seconds())
        try:
            chat_id = _get_my_chat_id()
            if not chat_id: continue

            tasks = get_all_tasks()
            today = date.today()
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
                lines.append(f"\n🟡 *Сегодня ({len(td_tasks)}):*")
                for t in td_tasks: lines.append(f"  • {t['title']}")
            if upcoming:
                lines.append(f"\n🟢 *Ближайшие ({len(upcoming)}):*")
                for t in upcoming[:3]:
                    lines.append(f"  • {t['title']} _{t['deadline']}_")

            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Все задачи",    callback_data="m:tasks:0:all"),
                 InlineKeyboardButton("🔴 Просроченные", callback_data="m:tasks:0:overdue")],
                [InlineKeyboardButton("🌐 Открыть приложение", url=WEBAPP_URL)],
            ])
            await bot.send_message(chat_id, "\n".join(lines), parse_mode="Markdown", reply_markup=kb)
        except Exception as e:
            logger.error(f"daily_reminders: {e}")

def _log(uid, uname, action, tid, title, changes):
    try:
        s = get_sheet(LOG_SHEET_NAME)
        s.append_row([datetime.now().isoformat(timespec="seconds"),uid,uname,action,tid,title,changes])
    except Exception as e:
        logger.warning(f"log: {e}")

# ══════════════════════════════════════════════════════
# STARTUP / WEBHOOK
# ══════════════════════════════════════════════════════
@app.on_event("startup")
async def startup():
    try:
        s = get_sheet()
        logger.info(f"✅ Sheets: {s.title}")
    except Exception as e:
        logger.error(f"❌ Sheets: {e}")
    asyncio.create_task(check_sheet_changes())
    asyncio.create_task(send_daily_reminders())
    logger.info("✅ Background tasks started")

@app.on_event("shutdown")
async def shutdown():
    await bot.close()

tg_app = None

@app.post("/webhook/{token}")
async def telegram_webhook(token: str, request: Request):
    if token != BOT_TOKEN: raise HTTPException(status_code=403)
    global tg_app
    if tg_app is None:
        tg_app = Application.builder().token(BOT_TOKEN).build()
        tg_app.add_handler(CommandHandler("start",  cmd_start))
        tg_app.add_handler(CommandHandler("tasks",  cmd_tasks))
        tg_app.add_handler(CommandHandler("today",  cmd_today))
        tg_app.add_handler(CommandHandler("add",    cmd_add))
        tg_app.add_handler(CommandHandler("done",   cmd_done))
        tg_app.add_handler(CommandHandler("stats",  cmd_stats))
        tg_app.add_handler(CommandHandler("help",   cmd_help))
        tg_app.add_handler(MessageHandler(filters.VOICE, handle_voice))
        tg_app.add_handler(CallbackQueryHandler(handle_callback))
        await tg_app.initialize()
    data   = await request.json()
    update = Update.de_json(data, bot)
    await tg_app.process_update(update)
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
