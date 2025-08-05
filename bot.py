import json
import os
import time
import requests
import asyncio
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)
from threading import Thread

# Хранилище user_id → JWT токен (можно заменить на БД)
user_tokens = {}

API_BASE_URL = "https://api.totothemoon.site/api"
POLLING_INTERVAL = 5  # секунд

# Приветственное сообщение
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я — Telegram-чат для твоего приложения Lify AI.\n\n"
        "Чтобы связать аккаунт, пришли мне свой telegram токен, который находится в твоем профиле в приложении.\n\n"
        "💡 Просто скопируй и вставь его — и сможешь писать сообщения.",
        parse_mode="Markdown"
    )

# Основная обработка сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # 1. Если токен ещё не сохранён — сохранить его
    if user_id not in user_tokens:
        if len(text.split(".")) == 3:  # простая проверка на JWT
            user_tokens[user_id] = text
            await update.message.reply_text("✅ Токен сохранён! Теперь можешь писать сообщения.")
        else:
            await update.message.reply_text(
                "🔑 Пришли мне свой telegram токен (JWT), который ты получил в приложении.\n\n"
                "💡 Просто вставь его сюда — без слова `Bearer`."
            )
        return

    # 2. Отправить сообщение в /Chat
    jwt_token = user_tokens[user_id]
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {jwt_token}"
    }
    payload = {"Message": text}

    try:
        post_response = requests.post(f"{API_BASE_URL}/Chat", headers=headers, json=payload)
        if post_response.status_code != 200:
            await update.message.reply_text(f"❌ Ошибка при отправке сообщения: {post_response.text}")
            return

        chat_msg = post_response.json()
        message_id = chat_msg["id"]

        await update.message.reply_text("🕐 Обрабатываю запрос...")

        # 3. Запускаем фоновый опрос
        Thread(target=poll_for_response, args=(user_id, message_id, context, jwt_token)).start()

    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

# Фоновый опрос до смены статуса
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

    # 4. Получить последний ответ от AI
    try:
        final_resp = requests.get(f"{API_BASE_URL}/Chat/Count/1/0", headers=headers)
        if final_resp.status_code != 200:
            send_message(context, user_id, f"❌ Ошибка при получении ответа: {final_resp.text}")
            return

        latest = final_resp.json()[0]
        ai_type = latest["type"]
        msg_text = latest["message"]

        # 5. Обработка ConfirmRequest
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
        send_message(context, user_id, f"❌ Ошибка получения финального ответа: {str(e)}")

# Упрощённый форматтер ConfirmRequest
def format_confirm_request(data):
    name = data.get("Name", "???")
    attributes = data.get("Attributes", [])
    result = [f"*{name}*"]

    for attr in attributes:
        key = attr.get("Key", "")
        value = attr.get("Value", "")
        result.append(f"*{key}*: {value}")

    return "\n".join(result)

# Асинхронная отправка сообщения
def send_message(context, user_id, text):
    loop = asyncio.get_event_loop()
    loop.create_task(context.bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown"))

# Запуск бота
def main():
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_BOT_TOKEN:
        print("❌ Не найден TELEGRAM_BOT_TOKEN в .env")
        return

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Бот запущен")
    app.run_polling()

if __name__ == "__main__":
    main()
