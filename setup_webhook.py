#!/usr/bin/env python3
"""
Скрипт для регистрации Telegram webhook
Запусти один раз после деплоя бэкенда
"""
import os
import requests

BOT_TOKEN = os.getenv("BOT_TOKEN") or input("Введи BOT_TOKEN: ")
SERVER_URL = os.getenv("SERVER_URL") or input("Введи URL сервера (https://...): ")

webhook_url = f"{SERVER_URL.rstrip('/')}/webhook/{BOT_TOKEN}"

resp = requests.post(
    f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
    json={"url": webhook_url, "allowed_updates": ["message", "callback_query"]}
)
data = resp.json()

if data.get("ok"):
    print(f"✅ Webhook установлен: {webhook_url}")
else:
    print(f"❌ Ошибка: {data}")

# Проверка
info = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo").json()
print(f"\nВебхук инфо: {info.get('result', {}).get('url')}")
