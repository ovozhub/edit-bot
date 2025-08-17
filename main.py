import os
import asyncio
from pathlib import Path
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ConversationHandler,
    MessageHandler, filters, ContextTypes
)
from telethon import TelegramClient
from telethon.tl.functions.channels import CreateChannelRequest

# 📂 sessions papkasini yaratamiz
Path("sessions").mkdir(exist_ok=True)

bot_token = "8350150569:AAEfax1UQn1AnpWrDdwFo0c7zCzDklkcbJk"
api_id = 25351311
api_hash = "7b854af9996797aa9ca67b42f1cd5cbe"

# Holatlar
ASK_PASSWORD, PHONE, CODE = range(3)
sessions = {}
ACCESS_PASSWORD = "dnx"

# Auto-guruh limit va interval
MAX_GROUPS = 500
AUTO_GROUP_INTERVAL = 0.5  # demo: 0.5s, haqiqiy: 86400

# Progress saqlash
progress = {}

# ——— START ———
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔒 Parolni kiriting:")
    return ASK_PASSWORD

async def ask_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip() != ACCESS_PASSWORD:
        await update.message.reply_text("❌ Noto‘g‘ri parol.")
        return ConversationHandler.END
    await update.message.reply_text("✅ Parol to‘g‘ri. Telefon raqamni yuboring:")
    return PHONE

async def phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    client = TelegramClient(f"sessions/{phone}", api_id, api_hash)
    sessions[update.effective_user.id] = client
    await client.connect()
    if not await client.is_user_authorized():
        await client.send_code_request(phone)
        await update.message.reply_text("📩 Kod yuborildi, kiriting:")
        context.user_data['phone'] = phone
        return CODE
    await update.message.reply_text("✅ Akkount allaqachon ulangan.")
    return await after_login(update, context)

async def code_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    client = sessions.get(update.effective_user.id)
    phone = context.user_data.get('phone')
    await client.sign_in(phone, update.message.text.strip())
    return await after_login(update, context)

async def after_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    progress[user_id] = 0
    msg = await update.message.reply_text(f"⏳ Guruhlar yaratilmoqda… [----------] 0%")
    asyncio.create_task(auto_group_task(user_id, context, msg))
    return ConversationHandler.END

# ——— Animatsiyali auto-guruh yaratish funksiyasi ———
async def auto_group_task(user_id, context, progress_msg):
    client = sessions[user_id]
    current = progress.get(user_id, 0)

    while current < MAX_GROUPS:
        to_create = min(50, MAX_GROUPS - current)
        for i in range(1, to_create + 1):
            current += 1
            progress[user_id] = current
            # Guruh yaratish
            try:
                await client(CreateChannelRequest(
                    title=f"Guruh #{current}", about="Guruh sotiladi", megagroup=True
                ))
            except Exception as e:
                await context.bot.send_message(user_id, f"❌ Guruh #{current} yaratishda xato: {e}")

            # Progress bar hisoblash
            percent = int(current / MAX_GROUPS * 100)
            bars = int(percent / 5)  # 20 bo'lakli bar
            bar_str = "■" * bars + "-" * (20 - bars)
            await progress_msg.edit_text(f"⏳ Guruhlar yaratilmoqda… [{bar_str}] {percent}%")

            await asyncio.sleep(0.5)  # demo

        if current >= MAX_GROUPS:
            await progress_msg.edit_text(f"✅ Maksimal limit {MAX_GROUPS} ga yetdi. Guruh yaratish tugadi.")
            break

        await asyncio.sleep(AUTO_GROUP_INTERVAL)

    await client.disconnect()
    sessions.pop(user_id, None)

# ——— Bekor qilish ———
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Bekor qilindi.")
    if (client := sessions.pop(update.effective_user.id, None)):
        await client.disconnect()
    return ConversationHandler.END

# ——— ASOSIY ———
async def main():
    application = Application.builder().token(bot_token).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_password)],
            PHONE: [MessageHandler(filters.TEXT, phone_received)],
            CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, code_received)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    application.add_handler(conv_handler)

    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
