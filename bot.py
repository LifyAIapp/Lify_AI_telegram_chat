import os
import json
import time
import requests
import asyncio
from threading import Thread
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# Telegram user_id → JWT token (в проде можно заменить на БД)
user_tokens = {}

API_BASE_URL = "https://api.totothemoon.site/api"
POLLING_INTERVAL = 5  # секунд

# Обработка входящих сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # 1. Сохраняем токен
    if user_id not in user_tokens:
        if text.lower().startswith("bearer "):
            token = text.split(" ", 1)[1]
            user_tokens[user_id] = token
            await update.message.reply_text("✅ Токен сохранён! Теперь можешь писать сообщения.")
        else:
            await update.message.reply_text("🔑 Отправь JWT токен в формате:\n`Bearer <твой_токен>`")
        return

    # 2. Отправляем сообщение в API
    jwt_token = user_tokens[user_id]
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {jwt_token}"
    }
    payload = {"Message": text}

    try:
        post_response = requests.post(f"{API_BASE_URL}/Chat", headers=headers, json=payload)
        if post_response.status_code != 200:
            await update.message.reply_text(f"❌ Ошибка при отправке: {post_response.text}")
            return

        chat_msg = post_response.json()
        message_id = chat_msg["id"]
        await update.message.reply_text("🕐 Обрабатываю запрос...")

        Thread(target=poll_for_response, args=(user_id, message_id, context, jwt_token)).start()

    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

# Опрос до смены статуса
def poll_for_response(user_id, message_id, context, jwt_token):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {jwt_token}"
    }

    while True:
        try:
            resp = requests.get(f"{API_BASE_URL}/Chat/{message_id}", headers=headers)
            if resp.status_code != 200:
                send_message(context, user_id, f"❌ Ошибка при проверке статуса: {resp.text}")
                return

            data = resp.json()
            if data["type"] != 1:  # 1 = Processing
                break
            time.sleep(POLLING_INTERVAL)
        except Exception as e:
            send_message(context, user_id, f"❌ Ошибка: {str(e)}")
            return

    # Получаем финальный ответ
    try:
        final_resp = requests.get(f"{API_BASE_URL}/Chat/Count/1/0", headers=headers)
        if final_resp.status_code != 200:
            send_message(context, user_id, f"❌ Ошибка при получении ответа: {final_resp.text}")
            return

        latest = final_resp.json()[0]
        ai_type = latest["type"]
        msg_text = latest["message"]

        if ai_type == 2:  # ConfirmRequest
            try:
                parsed = json.loads(msg_text)
                formatted = format_confirm_request(parsed)
                send_message(context, user_id, f"🤖 Подтверждение:\n\n{formatted}")
            except Exception:
                send_message(context, user_id, f"🤖 (ConfirmRequest, но не удалось разобрать JSON):\n{msg_text}")
        else:
            send_message(context, user_id, f"🤖 Ответ:\n{msg_text}")

    except Exception as e:
        send_message(context, user_id, f"❌ Ошибка финального запроса: {str(e)}")

# Форматирование ConfirmRequest
def format_confirm_request(data):
    name = data.get("Name", "???")
    attributes = data.get("Attributes", [])
    result = [f"**{name}**\n"]

    for attr in attributes:
        key = attr.get("Key", "")
        value = attr.get("Value", "")
        result.append(f"**{key}**: {value}")

    return "\n".join(result)

# Отправка в чат Telegram
def send_message(context, user_id, text):
    loop = asyncio.get_event_loop()
    loop.create_task(context.bot.send_message(chat_id=user_id, text=text))

# Точка входа
def main():
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_BOT_TOKEN:
        print("❌ Не найден TELEGRAM_BOT_TOKEN в .env")
        return

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Бот запущен")
    app.run_polling()

if __name__ == "__main__":
    main()
