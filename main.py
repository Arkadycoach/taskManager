"""
Task Manager Bot — полный бэкенд
Стек: FastAPI + python-telegram-bot + gspread + OpenAI Whisper + Claude AI
"""

import asyncio, json, logging, os, uuid, io, re
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

# ==========================================
# CONFIG
# ==========================================
BOT_TOKEN          = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
WEBAPP_URL         = os.getenv("WEBAPP_URL", "https://your-frontend-url.com")
SHEET_ID           = os.getenv("SHEET_ID", "YOUR_GOOGLE_SHEET_ID")
GOOGLE_CREDS_JSON  = os.getenv("GOOGLE_CREDS_JSON", "")
OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY", "")   # для Whisper
ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY", "") # для AI-парсинга команд

SHEET_NAME     = "Tasks"
LOG_SHEET_NAME = "ChangeLog"

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# ==========================================
# КОЛОНКИ
# ==========================================
COLUMNS = [
    "ID", "Название", "Описание", "Статус", "Приоритет",
    "Дедлайн", "Исполнитель", "UserID", "Имя пользователя",
    "Создано", "Обновлено", "ID Календаря"
]

STATUS_TO_RU   = {"todo": "Новая",    "doing": "В работе", "done": "Готово"}
STATUS_FROM_RU = {"Новая": "todo",    "В работе": "doing", "Готово": "done"}
PRIORITY_TO_RU   = {"low": "Низкий",  "medium": "Средний", "high": "Высокий"}
PRIORITY_FROM_RU = {"Низкий": "low",  "Средний": "medium", "Высокий": "high"}

STATUS_EMOJI   = {"todo": "🔵", "doing": "🟡", "done": "✅"}
PRIORITY_EMOJI = {"high": "🔴", "medium": "🟡", "low": "🟢"}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==========================================
# GOOGLE SHEETS
# ==========================================
def get_sheets_client():
    if GOOGLE_CREDS_JSON:
        creds_dict = json.loads(GOOGLE_CREDS_JSON)
    else:
        with open("service_account.json") as f:
            creds_dict = json.load(f)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)

def get_sheet(name=SHEET_NAME):
    client = get_sheets_client()
    spreadsheet = client.open_by_key(SHEET_ID)
    try:
        sheet = spreadsheet.worksheet(name)
        if name == SHEET_NAME:
            _ensure_headers(sheet, spreadsheet)
        return sheet
    except gspread.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title=name, rows=1000, cols=len(COLUMNS))
        if name == SHEET_NAME:
            sheet.append_row(COLUMNS)
            _setup_validation(spreadsheet, sheet)
        elif name == LOG_SHEET_NAME:
            sheet.append_row(["Время", "UserID", "Пользователь", "Действие",
                               "ID задачи", "Название задачи", "Изменения"])
        return sheet

def _ensure_headers(sheet, spreadsheet):
    try:
        row = sheet.row_values(1)
        if row and row[0] == "ID" and len(row) > 1 and row[1] == "Title":
            sheet.update('A1', [COLUMNS])
        if row and len(row) < 12:
            _setup_validation(spreadsheet, sheet)
    except Exception as e:
        logger.warning(f"_ensure_headers: {e}")

def _setup_validation(spreadsheet, sheet):
    try:
        sid = sheet.id
        requests = [
            {"updateSheetProperties": {
                "properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount"}},
            {"setDataValidation": {
                "range": {"sheetId": sid, "startRowIndex": 1, "endRowIndex": 1000,
                          "startColumnIndex": 3, "endColumnIndex": 4},
                "rule": {"condition": {"type": "ONE_OF_LIST", "values": [
                    {"userEnteredValue": "Новая"},
                    {"userEnteredValue": "В работе"},
                    {"userEnteredValue": "Готово"},
                ]}, "showCustomUi": True, "strict": True}}},
            {"setDataValidation": {
                "range": {"sheetId": sid, "startRowIndex": 1, "endRowIndex": 1000,
                          "startColumnIndex": 4, "endColumnIndex": 5},
                "rule": {"condition": {"type": "ONE_OF_LIST", "values": [
                    {"userEnteredValue": "Высокий"},
                    {"userEnteredValue": "Средний"},
                    {"userEnteredValue": "Низкий"},
                ]}, "showCustomUi": True, "strict": True}}},
        ]
        spreadsheet.batch_update({"requests": requests})
    except Exception as e:
        logger.error(f"_setup_validation: {e}")

def row_to_task(row: list) -> dict:
    def get(i): return row[i] if i < len(row) else ""
    raw_s = get(3); raw_p = get(4)
    status   = STATUS_FROM_RU.get(raw_s)   or (raw_s if raw_s in STATUS_TO_RU   else "todo")
    priority = PRIORITY_FROM_RU.get(raw_p) or (raw_p if raw_p in PRIORITY_TO_RU else "medium")
    return {
        "id": get(0), "title": get(1), "description": get(2),
        "status": status, "priority": priority,
        "deadline": get(5), "assignee": get(6),
        "user_id": get(7), "user_name": get(8),
        "created_at": get(9), "updated_at": get(10),
    }

# ==========================================
# PYDANTIC MODELS
# ==========================================
class TaskCreate(BaseModel):
    title: str
    description: str = ""
    status: str = "todo"
    priority: str = "medium"
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

# ==========================================
# FASTAPI
# ==========================================
app = FastAPI(title="Task Manager API")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

bot = Bot(token=BOT_TOKEN)
user_chat_ids: dict[str, int] = {}

@app.get("/tasks")
async def get_tasks(user_id: str = ""):
    try:
        sheet = get_sheet()
        all_rows = sheet.get_all_values()
        if len(all_rows) <= 1:
            return {"tasks": []}
        tasks = []
        for row in all_rows[1:]:
            if len(row) < 2 or not row[0]: continue
            tasks.append(row_to_task(row))
        return {"tasks": tasks}
    except Exception as e:
        logger.error(f"get_tasks: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/tasks")
async def create_task(task: TaskCreate, x_user_id: str = Header(default="")):
    try:
        sheet  = get_sheet()
        tid    = str(uuid.uuid4())[:8].upper()
        now    = datetime.now().isoformat(timespec="seconds")
        uid    = task.user_id or x_user_id
        row    = [
            tid, task.title, task.description,
            STATUS_TO_RU.get(task.status, task.status),
            PRIORITY_TO_RU.get(task.priority, task.priority),
            task.deadline, task.assignee,
            uid, task.user_name, now, now, ""
        ]
        sheet.append_row(row)
        new_task = {
            "id": tid, "title": task.title, "description": task.description,
            "status": task.status, "priority": task.priority,
            "deadline": task.deadline, "assignee": task.assignee,
            "user_id": uid, "user_name": task.user_name,
            "created_at": now, "updated_at": now,
        }
        _log(uid, task.user_name, "СОЗДАНИЕ", tid, task.title, f"Создана: {task.title}")
        # Уведомление
        await _notify_task_event("create", new_task, uid)
        return {"task": new_task}
    except Exception as e:
        logger.error(f"create_task: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/tasks/{task_id}")
async def update_task(task_id: str, update: TaskUpdate,
                      x_user_id: str = Header(default="")):
    try:
        sheet    = get_sheet()
        all_rows = sheet.get_all_values()
        row_idx  = None; old_task = None
        for i, row in enumerate(all_rows[1:], start=2):
            if row and row[0] == task_id:
                row_idx = i; old_task = row_to_task(row); break
        if row_idx is None:
            raise HTTPException(status_code=404, detail="Task not found")

        changes = []
        sl = {"todo": "Новая", "doing": "В работе", "done": "Готово"}
        pl = {"high": "Высокий", "medium": "Средний", "low": "Низкий"}

        if update.title is not None:
            sheet.update_cell(row_idx, 2, update.title)
            if old_task["title"] != update.title:
                changes.append(f"название: {old_task['title']} → {update.title}")
        if update.description is not None:
            sheet.update_cell(row_idx, 3, update.description)
        if update.status is not None:
            sheet.update_cell(row_idx, 4, STATUS_TO_RU.get(update.status, update.status))
            if old_task["status"] != update.status:
                changes.append(f"статус: {sl.get(old_task['status'])} → {sl.get(update.status)}")
        if update.priority is not None:
            sheet.update_cell(row_idx, 5, PRIORITY_TO_RU.get(update.priority, update.priority))
            if old_task["priority"] != update.priority:
                changes.append(f"приоритет: {pl.get(update.priority)}")
        if update.deadline is not None:
            sheet.update_cell(row_idx, 6, update.deadline)
            if old_task["deadline"] != update.deadline:
                changes.append(f"дедлайн: {update.deadline or 'убран'}")
        if update.assignee is not None:
            sheet.update_cell(row_idx, 7, update.assignee)
            if old_task["assignee"] != update.assignee:
                changes.append(f"исполнитель: {update.assignee or 'не назначен'}")

        now = datetime.now().isoformat(timespec="seconds")
        sheet.update_cell(row_idx, 11, now)

        uid = update.user_id or x_user_id
        updated_task = {**old_task, **(
            {k: v for k, v in {
                "title": update.title, "description": update.description,
                "status": update.status, "priority": update.priority,
                "deadline": update.deadline, "assignee": update.assignee,
            }.items() if v is not None}
        )}
        if changes:
            _log(uid, update.user_name, "ОБНОВЛЕНИЕ", task_id,
                 update.title or old_task["title"], "; ".join(changes))
            await _notify_task_event("update", updated_task, uid, changes)

        # Отдельное уведомление при выполнении
        if update.status == "done" and old_task["status"] != "done":
            await _notify_task_event("done", updated_task, uid)

        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"update_task: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/tasks/{task_id}")
async def delete_task(task_id: str, x_user_id: str = Header(default="")):
    try:
        sheet = get_sheet()
        all_rows = sheet.get_all_values()
        for i, row in enumerate(all_rows[1:], start=2):
            if row and row[0] == task_id:
                task_title = row[1] if len(row) > 1 else task_id
                deleted_task = row_to_task(row)
                sheet.delete_rows(i)
                _log(x_user_id, "", "УДАЛЕНИЕ", task_id, task_title, "Задача удалена")
                await _notify_task_event("delete", deleted_task, x_user_id)
                return {"success": True}
        raise HTTPException(status_code=404, detail="Task not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"delete_task: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/register")
async def register_user(data: dict):
    uid = str(data.get("user_id", ""))
    cid = data.get("chat_id")
    if uid and cid:
        user_chat_ids[uid] = int(cid)
    return {"ok": True}

@app.post("/admin/setup-sheet")
async def admin_setup_sheet():
    try:
        client = get_sheets_client()
        sp     = client.open_by_key(SHEET_ID)
        sheet  = sp.worksheet(SHEET_NAME)
        sheet.update('A1', [COLUMNS])
        _setup_validation(sp, sheet)
        return {"success": True, "message": "Лист настроен"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ==========================================
# УВЕДОМЛЕНИЯ В TELEGRAM
# ==========================================
async def _notify_task_event(event: str, task: dict, actor_uid: str,
                              changes: list = None):
    """Отправляет красивое уведомление в Telegram при событии задачи."""
    se = STATUS_EMOJI.get(task.get("status","todo"), "🔵")
    pe = PRIORITY_EMOJI.get(task.get("priority","medium"), "🟡")
    title = task.get("title","")
    dl    = task.get("deadline","")
    asgn  = task.get("assignee","")
    dl_str = f"\n📅 Дедлайн: {dl}" if dl else ""
    asgn_str = f"\n👤 Исполнитель: {asgn}" if asgn else ""

    if event == "create":
        text = (
            f"✅ *Новая задача создана*\n\n"
            f"{pe} *{title}*\n"
            f"{se} Статус: {STATUS_TO_RU.get(task['status'],'')}"
            f"{dl_str}{asgn_str}"
        )
    elif event == "done":
        text = (
            f"🎉 *Задача выполнена!*\n\n"
            f"✅ *{title}*\n\n"
            f"Отличная работа! 💪"
        )
    elif event == "update":
        ch_text = "\n".join(f"  • {c}" for c in (changes or []))
        text = (
            f"✏️ *Задача обновлена*\n\n"
            f"*{title}*\n\n"
            f"{ch_text}"
        )
    elif event == "delete":
        text = f"🗑 *Задача удалена*\n\n~~{title}~~"
    elif event == "sheets_update":
        ch_text = "\n".join(f"  • {c}" for c in (changes or []))
        text = (
            f"📊 *Изменение в Google Sheets*\n\n"
            f"*{title}*\n\n"
            f"{ch_text}"
        )
    else:
        return

    # Кнопки действий (только для актуальных задач)
    keyboard = None
    if event in ("create", "sheets_update", "update") and task.get("id"):
        tid = task["id"]
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("▶️ В работу",    callback_data=f"doing:{tid}"),
                InlineKeyboardButton("✅ Выполнено",   callback_data=f"done:{tid}"),
            ],
            [InlineKeyboardButton("📋 Открыть приложение", url=WEBAPP_URL)],
        ])

    # Отправляем всем зарегистрированным пользователям (или конкретному)
    recipients = list(user_chat_ids.items())
    if not recipients:
        return

    # Если есть конкретный инициатор — отправляем всем кроме него
    # (или всем — зависит от логики)
    for uid, chat_id in recipients:
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
        except Exception as e:
            logger.warning(f"notify {uid}: {e}")

# ==========================================
# ГОЛОСОВОЙ АССИСТЕНТ
# ==========================================
async def transcribe_voice(voice_bytes: bytes, filename: str = "voice.ogg") -> str:
    """Расшифровывает голосовое через OpenAI Whisper."""
    if not OPENAI_API_KEY:
        return ""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                files={"file": (filename, voice_bytes, "audio/ogg")},
                data={"model": "whisper-1", "language": "ru"},
            )
            resp.raise_for_status()
            return resp.json().get("text", "")
    except Exception as e:
        logger.error(f"transcribe_voice: {e}")
        return ""

async def parse_voice_command(text: str, tasks_summary: str) -> dict:
    """
    Использует Claude для понимания голосовой команды.
    Возвращает dict с action и параметрами.
    """
    if not ANTHROPIC_API_KEY:
        return {"action": "unknown", "raw": text}

    system_prompt = """Ты — AI-ассистент таск-менеджера. Пользователь говорит голосовую команду на русском.
Твоя задача: разобрать команду и вернуть ТОЛЬКО валидный JSON (без markdown, без пояснений).

Возможные actions:
- create_task: создать задачу
- update_task: обновить существующую задачу
- complete_task: отметить задачу выполненной
- delete_task: удалить задачу
- list_tasks: показать список задач
- get_stats: показать статистику
- unknown: непонятная команда

Формат ответа для create_task:
{"action":"create_task","title":"...","description":"...","priority":"high|medium|low","deadline":"YYYY-MM-DD или пусто","assignee":"..."}

Формат для update_task:
{"action":"update_task","search_title":"...","updates":{"title":"...","status":"todo|doing|done","priority":"...","deadline":"...","assignee":"..."}}

Формат для complete_task:
{"action":"complete_task","search_title":"..."}

Формат для delete_task:
{"action":"delete_task","search_title":"..."}

Формат для list_tasks / get_stats:
{"action":"list_tasks"} или {"action":"get_stats"}

Правила для дат: "завтра"=завтра, "пятница"=ближайшая пятница, "через неделю"=+7 дней. Дата сегодня: """ + date.today().isoformat()

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 512,
                    "system": system_prompt,
                    "messages": [{
                        "role": "user",
                        "content": f"Команда: {text}\n\nТекущие задачи:\n{tasks_summary}"
                    }]
                }
            )
            resp.raise_for_status()
            content = resp.json()["content"][0]["text"].strip()
            # Убираем markdown-обёртку если есть
            content = re.sub(r"```json\s*|\s*```", "", content).strip()
            return json.loads(content)
    except Exception as e:
        logger.error(f"parse_voice_command: {e}")
        return {"action": "unknown", "raw": text}

async def execute_voice_action(action_data: dict, user_id: str,
                                user_name: str) -> str:
    """Выполняет распознанную команду и возвращает текст ответа."""
    action = action_data.get("action", "unknown")

    if action == "create_task":
        title = action_data.get("title", "Новая задача")
        task  = TaskCreate(
            title       = title,
            description = action_data.get("description", ""),
            priority    = action_data.get("priority", "medium"),
            deadline    = action_data.get("deadline", ""),
            assignee    = action_data.get("assignee", ""),
            user_id     = user_id,
            user_name   = user_name,
        )
        sheet  = get_sheet()
        tid    = str(uuid.uuid4())[:8].upper()
        now    = datetime.now().isoformat(timespec="seconds")
        row    = [
            tid, task.title, task.description,
            STATUS_TO_RU.get(task.status, task.status),
            PRIORITY_TO_RU.get(task.priority, task.priority),
            task.deadline, task.assignee,
            user_id, user_name, now, now, ""
        ]
        sheet.append_row(row)
        pe   = PRIORITY_EMOJI.get(task.priority, "🟡")
        dl   = f"\n📅 Дедлайн: {task.deadline}" if task.deadline else ""
        return (
            f"✅ *Задача создана!*\n\n"
            f"{pe} *{title}*{dl}\n\n"
            f"🆔 ID: `{tid}`"
        )

    elif action in ("complete_task", "update_task", "delete_task"):
        search = action_data.get("search_title", "")
        sheet  = get_sheet()
        rows   = sheet.get_all_values()
        # Ищем задачу по частичному совпадению названия
        found_idx  = None; found_task = None
        for i, row in enumerate(rows[1:], start=2):
            if row and row[1] and search.lower() in row[1].lower():
                found_idx = i; found_task = row_to_task(row); break

        if not found_task:
            return f"❌ Задача «{search}» не найдена.\n\nПопробуй /tasks чтобы увидеть все задачи."

        if action == "complete_task":
            sheet.update_cell(found_idx, 4, "Готово")
            sheet.update_cell(found_idx, 11, datetime.now().isoformat(timespec="seconds"))
            await _notify_task_event("done", found_task, user_id)
            return f"🎉 *Задача выполнена!*\n\n✅ {found_task['title']}"

        elif action == "delete_task":
            sheet.delete_rows(found_idx)
            return f"🗑 Задача удалена:\n~~{found_task['title']}~~"

        elif action == "update_task":
            updates = action_data.get("updates", {})
            changes = []
            if "title" in updates:
                sheet.update_cell(found_idx, 2, updates["title"]); changes.append(f"название → {updates['title']}")
            if "status" in updates:
                sheet.update_cell(found_idx, 4, STATUS_TO_RU.get(updates["status"], updates["status"]))
                changes.append(f"статус → {STATUS_TO_RU.get(updates['status'])}")
            if "priority" in updates:
                sheet.update_cell(found_idx, 5, PRIORITY_TO_RU.get(updates["priority"], updates["priority"]))
                changes.append(f"приоритет → {PRIORITY_TO_RU.get(updates['priority'])}")
            if "deadline" in updates:
                sheet.update_cell(found_idx, 6, updates["deadline"]); changes.append(f"дедлайн → {updates['deadline']}")
            if "assignee" in updates:
                sheet.update_cell(found_idx, 7, updates["assignee"]); changes.append(f"исполнитель → {updates['assignee']}")
            sheet.update_cell(found_idx, 11, datetime.now().isoformat(timespec="seconds"))
            ch = "\n  • ".join(changes)
            return f"✏️ *Задача обновлена*\n\n*{found_task['title']}*\n\n  • {ch}"

    elif action == "list_tasks":
        return await _format_tasks_list(user_id)

    elif action == "get_stats":
        return await _format_stats(user_id)

    else:
        raw = action_data.get("raw", "")
        return (
            f"🤔 Не понял команду.\n\n"
            f"Попробуй сказать:\n"
            f"• «Создай задачу: написать отчёт, высокий приоритет»\n"
            f"• «Отметь задачу встреча как выполненную»\n"
            f"• «Обнови задачу отчёт, дедлайн пятница»\n"
            f"• «Покажи мои задачи»"
        )

async def _format_tasks_list(user_id: str) -> str:
    sheet = get_sheet()
    rows  = sheet.get_all_values()
    tasks = [row_to_task(r) for r in rows[1:] if r and r[0] and row_to_task(r)["status"] != "done"]
    if not tasks:
        return "✅ Нет активных задач!"
    lines = [f"📋 *Активные задачи ({len(tasks)}):*\n"]
    for t in tasks[:10]:
        se = STATUS_EMOJI.get(t["status"], "•")
        pe = PRIORITY_EMOJI.get(t["priority"], "")
        dl = f" _({t['deadline']})_" if t["deadline"] else ""
        lines.append(f"{se}{pe} {t['title']}{dl}")
    if len(tasks) > 10:
        lines.append(f"\n_... и ещё {len(tasks)-10}_")
    return "\n".join(lines)

async def _format_stats(user_id: str) -> str:
    sheet = get_sheet()
    rows  = sheet.get_all_values()
    tasks = [row_to_task(r) for r in rows[1:] if r and r[0]]
    total = len(tasks)
    by_s  = {"todo": 0, "doing": 0, "done": 0}
    overdue = 0; today = date.today()
    for t in tasks:
        by_s[t["status"]] = by_s.get(t["status"], 0) + 1
        if t["deadline"] and t["status"] != "done":
            try:
                if date.fromisoformat(t["deadline"]) < today: overdue += 1
            except ValueError: pass
    pct = round(by_s["done"] / total * 100) if total else 0
    return (
        f"📊 *Статистика*\n\n"
        f"Всего: *{total}*\n"
        f"├ 🔵 Новые: {by_s['todo']}\n"
        f"├ 🟡 В работе: {by_s['doing']}\n"
        f"└ ✅ Готово: {by_s['done']}\n\n"
        f"🔴 Просрочено: {overdue}\n"
        f"📈 Прогресс: *{pct}%*"
    )

# ==========================================
# SHEETS → APP POLLING
# ==========================================
_last_sheet_state: dict[str, dict] = {}

async def check_sheet_changes():
    global _last_sheet_state
    while True:
        await asyncio.sleep(60)
        try:
            sheet = get_sheet()
            rows  = sheet.get_all_values()
            current = {}
            for row in rows[1:]:
                if row and row[0]:
                    t = row_to_task(row); current[t["id"]] = t

            if _last_sheet_state:
                # Изменённые задачи
                for tid, task in current.items():
                    if tid in _last_sheet_state:
                        old = _last_sheet_state[tid]; changes = []
                        if old["title"]    != task["title"]:    changes.append(f"📝 Название: *{task['title']}*")
                        if old["status"]   != task["status"]:   changes.append(f"🔄 Статус: {STATUS_TO_RU.get(old['status'])} → *{STATUS_TO_RU.get(task['status'])}*")
                        if old["priority"] != task["priority"]: changes.append(f"⚡ Приоритет: {PRIORITY_TO_RU.get(task['priority'])}")
                        if old["deadline"] != task["deadline"]: changes.append(f"📅 Дедлайн: *{task['deadline'] or 'убран'}*")
                        if old["assignee"] != task["assignee"]: changes.append(f"👤 Исполнитель: *{task['assignee'] or 'не назначен'}*")
                        if changes:
                            await _notify_task_event("sheets_update", task, "", changes)
                    else:
                        # Новая задача добавлена прямо в Sheets
                        await _notify_task_event("create", task, "")

                # Удалённые задачи
                for tid in _last_sheet_state:
                    if tid not in current:
                        await _notify_task_event("delete", _last_sheet_state[tid], "")

            _last_sheet_state = current
        except Exception as e:
            logger.error(f"check_sheet_changes: {e}")

# ==========================================
# DAILY REMINDERS
# ==========================================
async def send_daily_reminders():
    while True:
        now = datetime.now()
        next_9 = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if now >= next_9: next_9 += timedelta(days=1)
        await asyncio.sleep((next_9 - now).total_seconds())
        try:
            sheet = get_sheet()
            rows  = sheet.get_all_values()
            today = date.today()
            user_tasks: dict[str, dict] = {}
            for row in rows[1:]:
                if not row or not row[0]: continue
                t = row_to_task(row)
                if t["status"] == "done": continue
                uid = t["user_id"]
                if uid not in user_tasks:
                    user_tasks[uid] = {"overdue": [], "today": [], "upcoming": []}
                if t["deadline"]:
                    try:
                        dl = date.fromisoformat(t["deadline"])
                        if   dl < today: user_tasks[uid]["overdue"].append(t)
                        elif dl == today: user_tasks[uid]["today"].append(t)
                        elif dl <= today + timedelta(days=3): user_tasks[uid]["upcoming"].append(t)
                    except ValueError: pass
                elif t["status"] == "doing":
                    user_tasks[uid]["upcoming"].append(t)

            for uid, buckets in user_tasks.items():
                cid = user_chat_ids.get(uid)
                if not cid: continue
                total_urgent = len(buckets["overdue"]) + len(buckets["today"])
                if total_urgent == 0 and not buckets["upcoming"]: continue
                lines = [f"☀️ *Доброе утро! {today.strftime('%d.%m.%Y')}*\n"]
                if buckets["overdue"]:
                    lines.append(f"🔴 *Просрочено ({len(buckets['overdue'])}):*")
                    for t in buckets["overdue"][:5]:
                        lines.append(f"  • {t['title']} _{t['deadline']}_")
                if buckets["today"]:
                    lines.append(f"\n🟡 *Сегодня ({len(buckets['today'])}):*")
                    for t in buckets["today"]: lines.append(f"  • {t['title']}")
                if buckets["upcoming"]:
                    lines.append(f"\n🟢 *Ближайшие ({len(buckets['upcoming'])}):*")
                    for t in buckets["upcoming"][:3]:
                        dl = f" _{t['deadline']}_" if t["deadline"] else ""
                        lines.append(f"  • {t['title']}{dl}")
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton("📋 Открыть задачи", url=WEBAPP_URL)
                ]])
                await bot.send_message(cid, "\n".join(lines),
                                       parse_mode="Markdown", reply_markup=kb)
        except Exception as e:
            logger.error(f"daily_reminders: {e}")

# ==========================================
# TELEGRAM HANDLERS
# ==========================================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user   = update.effective_user
    cid    = update.effective_chat.id
    uid    = str(user.id)
    user_chat_ids[uid] = cid

    await bot.set_my_commands([
        BotCommand("start",  "Открыть Task Manager"),
        BotCommand("tasks",  "Активные задачи"),
        BotCommand("add",    "Добавить задачу"),
        BotCommand("done",   "Отметить выполненной"),
        BotCommand("stats",  "Статистика"),
        BotCommand("help",   "Помощь"),
    ])

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("📋 Открыть Task Manager", web_app={"url": WEBAPP_URL})
    ]])
    await update.message.reply_text(
        f"👋 Привет, *{user.first_name}*\\!\n\n"
        "Я умный ассистент для управления задачами\\.\n\n"
        "🎙️ *Отправь голосовое* — я создам задачу\n"
        "📊 Всё синхронизируется с Google Sheets\n"
        "🔔 Уведомления при каждом изменении\n"
        "✏️ Редактируй задачи прямо в таблице\\!",
        parse_mode="MarkdownV2",
        reply_markup=kb,
    )

async def cmd_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    user_chat_ids[uid] = update.effective_chat.id
    text = await _format_tasks_list(uid)
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("📋 Открыть приложение", web_app={"url": WEBAPP_URL})
    ]])
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)

async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /add Название задачи @исполнитель !высокий 2025-06-15
    """
    uid  = str(update.effective_user.id)
    uname = update.effective_user.username or update.effective_user.first_name
    user_chat_ids[uid] = update.effective_chat.id
    args = context.args
    if not args:
        await update.message.reply_text(
            "📝 *Формат команды:*\n"
            "`/add Название !приоритет @исполнитель 2025-06-15`\n\n"
            "*Примеры:*\n"
            "`/add Написать отчёт !высокий`\n"
            "`/add Встреча с клиентом @иван 2025-06-10`\n"
            "`/add Проверить почту !низкий`",
            parse_mode="Markdown"
        )
        return
    raw      = " ".join(args)
    priority = "medium"
    assignee = ""
    deadline = ""
    # Парсим !приоритет
    p_map = {"!высокий": "high", "!срочно": "high",
             "!средний": "medium", "!низкий": "low"}
    for key, val in p_map.items():
        if key in raw.lower(): priority = val; raw = re.sub(re.escape(key), "", raw, flags=re.IGNORECASE)
    # Парсим @исполнитель
    m = re.search(r"@(\S+)", raw)
    if m: assignee = m.group(1); raw = raw.replace(m.group(0), "")
    # Парсим дату YYYY-MM-DD
    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", raw)
    if m: deadline = m.group(1); raw = raw.replace(m.group(0), "")
    title = raw.strip()
    if not title:
        await update.message.reply_text("❌ Укажи название задачи.")
        return

    sheet = get_sheet()
    tid   = str(uuid.uuid4())[:8].upper()
    now   = datetime.now().isoformat(timespec="seconds")
    sheet.append_row([
        tid, title, "",
        STATUS_TO_RU["todo"],
        PRIORITY_TO_RU[priority],
        deadline, assignee, uid, uname, now, now, ""
    ])
    pe   = PRIORITY_EMOJI[priority]
    dl   = f"\n📅 {deadline}" if deadline else ""
    asgn = f"\n👤 @{assignee}" if assignee else ""
    await update.message.reply_text(
        f"✅ *Задача добавлена!*\n\n{pe} *{title}*{dl}{asgn}\n\n🆔 `{tid}`",
        parse_mode="Markdown"
    )

async def cmd_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /done ID_задачи или /done часть названия
    """
    uid  = str(update.effective_user.id)
    user_chat_ids[uid] = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("Укажи ID или название: `/done A3F9C2D1`", parse_mode="Markdown")
        return
    query = " ".join(context.args).strip()
    sheet = get_sheet()
    rows  = sheet.get_all_values()
    found_idx = None; found_task = None
    for i, row in enumerate(rows[1:], start=2):
        if not row or not row[0]: continue
        if row[0].upper() == query.upper() or (row[1] and query.lower() in row[1].lower()):
            found_idx = i; found_task = row_to_task(row); break
    if not found_task:
        await update.message.reply_text(f"❌ Задача «{query}» не найдена.")
        return
    sheet.update_cell(found_idx, 4, "Готово")
    sheet.update_cell(found_idx, 11, datetime.now().isoformat(timespec="seconds"))
    await _notify_task_event("done", found_task, uid)
    await update.message.reply_text(
        f"🎉 *Выполнено!*\n\n✅ {found_task['title']}",
        parse_mode="Markdown"
    )

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    await update.message.reply_text(await _format_stats(uid), parse_mode="Markdown")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 *Task Manager — команды:*\n\n"
        "/start — главное меню\n"
        "/tasks — активные задачи\n"
        "/add Название \\!приоритет @исполнитель — добавить\n"
        "/done ID — отметить выполненной\n"
        "/stats — статистика\n\n"
        "🎙️ *Голосовой ассистент:*\n"
        "Просто отправь голосовое сообщение\\!\n\n"
        "_Примеры:_\n"
        "«Создай задачу встреча с клиентом высокий приоритет»\n"
        "«Отметь задачу отчёт как выполненную»\n"
        "«Обнови дедлайн задачи встреча на пятницу»\n"
        "«Покажи мои задачи»",
        parse_mode="MarkdownV2",
    )

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик голосовых сообщений."""
    uid   = str(update.effective_user.id)
    uname = update.effective_user.username or update.effective_user.first_name
    user_chat_ids[uid] = update.effective_chat.id

    if not OPENAI_API_KEY:
        await update.message.reply_text(
            "❌ Голосовой ассистент не настроен.\n\n"
            "Добавь `OPENAI_API_KEY` в переменные окружения."
        )
        return

    # Статус «печатаю...»
    await update.message.reply_chat_action("typing")
    processing_msg = await update.message.reply_text("🎙️ _Слушаю..._", parse_mode="Markdown")

    try:
        # 1. Скачиваем голосовое
        voice_file = await update.message.voice.get_file()
        voice_bytes = await voice_file.download_as_bytearray()

        # 2. Транскрибируем
        await processing_msg.edit_text("🎙️ _Распознаю речь..._", parse_mode="Markdown")
        transcript = await transcribe_voice(bytes(voice_bytes))

        if not transcript:
            await processing_msg.edit_text("❌ Не удалось распознать речь. Попробуй ещё раз.")
            return

        await processing_msg.edit_text(
            f"🎙️ _Распознано:_ «{transcript}»\n⚙️ _Выполняю..._",
            parse_mode="Markdown"
        )

        # 3. Парсим команду через Claude
        sheet = get_sheet()
        rows  = sheet.get_all_values()
        tasks_list = [row_to_task(r) for r in rows[1:] if r and r[0] and row_to_task(r)["status"] != "done"]
        tasks_summary = "\n".join(
            f"- [{t['id']}] {t['title']} ({STATUS_TO_RU.get(t['status'])})"
            for t in tasks_list[:20]
        )

        action_data = await parse_voice_command(transcript, tasks_summary)

        # 4. Выполняем
        result = await execute_voice_action(action_data, uid, uname)

        # 5. Отвечаем
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("📋 Открыть приложение", web_app={"url": WEBAPP_URL})
        ]])
        await processing_msg.edit_text(result, parse_mode="Markdown", reply_markup=kb)

    except Exception as e:
        logger.error(f"handle_voice: {e}")
        await processing_msg.edit_text(
            f"❌ Ошибка при обработке голосового сообщения.\n\n`{str(e)[:200]}`",
            parse_mode="Markdown"
        )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопок в сообщениях (В работу / Выполнено)."""
    query = update.callback_query
    await query.answer()
    uid   = str(query.from_user.id)
    uname = query.from_user.username or query.from_user.first_name

    data  = query.data  # "doing:TASKID" или "done:TASKID"
    parts = data.split(":")
    if len(parts) != 2:
        return
    new_status, task_id = parts[0], parts[1]

    try:
        sheet = get_sheet()
        rows  = sheet.get_all_values()
        for i, row in enumerate(rows[1:], start=2):
            if row and row[0] == task_id:
                sheet.update_cell(i, 4, STATUS_TO_RU.get(new_status, new_status))
                sheet.update_cell(i, 11, datetime.now().isoformat(timespec="seconds"))
                task = row_to_task(row)
                sl   = {"todo": "Новая", "doing": "В работе", "done": "Готово"}
                se   = STATUS_EMOJI.get(new_status, "🔵")

                if new_status == "done":
                    await query.edit_message_text(
                        f"🎉 *Выполнено!*\n\n✅ {task['title']}",
                        parse_mode="Markdown"
                    )
                    await _notify_task_event("done", task, uid)
                else:
                    await query.edit_message_text(
                        f"{se} *{sl[new_status]}*\n\n{task['title']}",
                        parse_mode="Markdown"
                    )
                return
    except Exception as e:
        logger.error(f"handle_callback: {e}")

def _log(uid, uname, action, tid, title, changes):
    try:
        sheet = get_sheet(LOG_SHEET_NAME)
        sheet.append_row([
            datetime.now().isoformat(timespec="seconds"),
            uid, uname, action, tid, title, changes
        ])
    except Exception as e:
        logger.warning(f"log error: {e}")

# ==========================================
# STARTUP
# ==========================================
@app.on_event("startup")
async def startup():
    try:
        sheet = get_sheet()
        logger.info(f"✅ Sheets: {sheet.title}")
    except Exception as e:
        logger.error(f"❌ Sheets: {e}")
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
        telegram_app = Application.builder().token(BOT_TOKEN).build()
        telegram_app.add_handler(CommandHandler("start",  cmd_start))
        telegram_app.add_handler(CommandHandler("tasks",  cmd_tasks))
        telegram_app.add_handler(CommandHandler("add",    cmd_add))
        telegram_app.add_handler(CommandHandler("done",   cmd_done))
        telegram_app.add_handler(CommandHandler("stats",  cmd_stats))
        telegram_app.add_handler(CommandHandler("help",   cmd_help))
        # Голосовые сообщения
        telegram_app.add_handler(MessageHandler(filters.VOICE, handle_voice))
        # Кнопки
        telegram_app.add_handler(CallbackQueryHandler(handle_callback))
        await telegram_app.initialize()
    data   = await request.json()
    update = Update.de_json(data, bot)
    await telegram_app.process_update(update)
    return {"ok": True}

@app.get("/health")
async def health():
    return {"status": "ok", "time": datetime.now().isoformat()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
