import json
import os
import requests
import asyncio
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")
PORT = int(os.environ.get("PORT", 8443))

API_BASE_URL = "https://api.totothemoon.site/api"
POLLING_INTERVAL = 5  # seconds

# Хранилище user_id → JWT токен
user_tokens = {}

# Стартовое сообщение
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я — Telegram-чат для твоего приложения Lify AI.\n\n"
        "Чтобы связать аккаунт, пришли мне свой telegram токен, который находится в твоем профиле в приложении.\n\n"
        "💡 Просто скопируй и вставь его — и сможешь писать сообщения."
    )

# Обработка сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if user_id not in user_tokens:
        if len(text.split(".")) == 3:
            user_tokens[user_id] = text
            await update.message.reply_text("✅ Токен сохранён! Теперь можешь писать сообщения.")
        else:
            await update.message.reply_text(
                "🔑 Пришли мне свой telegram токен (JWT), который ты получил в приложении.\n\n"
                "💡 Просто вставь его сюда — без слова `Bearer`.",
                parse_mode="Markdown"
            )
        return

    jwt_token = user_tokens[user_id]
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {jwt_token}"
    }

    user_id_str = f"tg:{str(user_id)}"  # строго строкой
    payload = {
        "Message": text,
        "Attributes": {
            "userIds": [user_id_str]
        }
    }

    try:
        post_response = requests.post(f"{API_BASE_URL}/Chat", headers=headers, json=payload)
        if post_response.status_code != 200:
            await update.message.reply_text(f"❌ Ошибка: {post_response.text}")
            return

        chat_msg = post_response.json()
        message_id = chat_msg["id"]

        await update.message.reply_text("🕐 Обрабатываю запрос...")

        # Запускаем фоновую async-задачу
        context.application.create_task(
            poll_for_response(user_id, message_id, context.application, jwt_token)
        )

    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

# Ожидание ответа
async def poll_for_response(user_id, message_id, application, jwt_token):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {jwt_token}"
    }

    while True:
        try:
            resp = requests.get(f"{API_BASE_URL}/Chat/{message_id}", headers=headers)
            if resp.status_code != 200:
                await application.bot.send_message(chat_id=user_id, text=f"❌ Ошибка: {resp.text}")
                return

            data = resp.json()
            if data.get("type") != 1:
                break
            await asyncio.sleep(POLLING_INTERVAL)
        except Exception as e:
            await application.bot.send_message(chat_id=user_id, text=f"❌ Ошибка: {str(e)}")
            return

    try:
        final_resp = requests.get(f"{API_BASE_URL}/Chat/Count/1/0", headers=headers)
        if final_resp.status_code != 200:
            await application.bot.send_message(chat_id=user_id, text=f"❌ Ошибка: {final_resp.text}")
            return

        latest = final_resp.json()[0]
        ai_type = latest.get("type")
        msg_text = latest.get("message", "")

        if ai_type == 2:
            try:
                parsed = json.loads(msg_text)
                formatted = format_confirm_request(parsed)
                await application.bot.send_message(chat_id=user_id, text=f"🤖 Подтверждение:\n\n{formatted}", parse_mode="Markdown")
            except Exception:
                await application.bot.send_message(chat_id=user_id, text=f"🤖 ConfirmRequest, но не удалось разобрать JSON:\n{msg_text}")
        else:
            await application.bot.send_message(chat_id=user_id, text=f"🤖 Ответ:\n{msg_text}")

    except Exception as e:
        await application.bot.send_message(chat_id=user_id, text=f"❌ Ошибка: {str(e)}")

# Форматирование ConfirmRequest
def format_confirm_request(data):
    name = data.get("Name", "???")
    attributes = data.get("Attributes", [])
    result = [f"*{name}*"]
    for attr in attributes:
        key = attr.get("Key", "")
        value = attr.get("Value", "")
        result.append(f"*{key}*: {value}")
    return "\n".join(result)

# Основной запуск
def main():
    if not TELEGRAM_BOT_TOKEN or not WEBHOOK_HOST:
        print("❌ .env не заполнен!")
        return

    path = WEBHOOK_PATH if WEBHOOK_PATH.startswith("/") else f"/{WEBHOOK_PATH}"
    webhook_url = f"{WEBHOOK_HOST.rstrip('/')}{path}"

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print(f"📡 Запуск webhook: {webhook_url}")
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=path,
        webhook_url=webhook_url,
        drop_pending_updates=True
    )

if __name__ == "__main__":
    main()
