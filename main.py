import logging
import asyncio
import os
from pathlib import Path
from aiohttp import web
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ConversationHandler, 
    MessageHandler, filters, ContextTypes
)
from telethon import TelegramClient, errors
from telethon.tl.functions.channels import CreateChannelRequest, InviteToChannelRequest

# 📂 session va progress fayllari
Path("sessions").mkdir(exist_ok=True)

# Telegram API
api_id = 25351311
api_hash = "7b854af9996797aa9ca67b42f1cd5cbe"
bot_token = "8350150569:AAEfax1UQn1AnpWrDdwFo0c7zCzDklkcbJk"

ACCESS_PASSWORD = "dnx"
TARGET_BOT = "@oxang_bot"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ASK_PASSWORD, SELECT_MODE, PHONE, CODE, PASSWORD, GROUP_RANGE = range(6)

sessions = {}
authorized_users = set()
progress = {}  # foydalanuvchi progressi
MAX_GROUPS = 500  # maksimal guruh

# ——— START ———
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id in authorized_users:
        return await show_menu(update)
    await update.message.reply_text("🔒 Kirish parolini kiriting:")
    return ASK_PASSWORD

async def ask_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip() != ACCESS_PASSWORD:
        await update.message.reply_text("❌ Noto‘g‘ri parol.")
        return ConversationHandler.END
    authorized_users.add(update.effective_user.id)
    return await show_menu(update)

async def show_menu(update: Update):
    keyboard = [[
        InlineKeyboardButton("Guruh ochish", callback_data='create_group')
    ]]
    target = update.message or update.callback_query.message
    await target.reply_text("Rejimni tanlang⚙️", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT_MODE

async def mode_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['mode'] = query.data
    keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton("📱 Telefon raqamni yuborish", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )
    await query.message.reply_text("📞 Telefon raqamingizni yuboring:", reply_markup=keyboard)
    return PHONE

async def phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.contact.phone_number if update.message.contact else update.message.text.strip()
    if not phone.startswith('+') or not phone[1:].isdigit():
        await update.message.reply_text("Telefon raqam + bilan boshlanishi va raqam bo‘lishi kerak.")
        return PHONE

    context.user_data['phone'] = phone
    client = TelegramClient(f"sessions/{phone}", api_id, api_hash)
    sessions[update.effective_user.id] = client

    await client.connect()
    if not await client.is_user_authorized():
        try:
            await client.send_code_request(phone)
            await update.message.reply_text("📩 Kod yuborildi, kiriting:")
            return CODE
        except Exception as e:
            await update.message.reply_text(f"❌ Xato: {e}")
            return ConversationHandler.END
    await update.message.reply_text("✅ Akkount allaqachon ulangan.")
    return await after_login(update, context)

async def code_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    client = sessions.get(update.effective_user.id)
    phone = context.user_data.get('phone')
    try:
        await client.sign_in(phone, update.message.text.strip())
    except errors.SessionPasswordNeededError:
        await update.message.reply_text("🔑 2 bosqichli parolni kiriting:")
        return PASSWORD
    except Exception as e:
        await update.message.reply_text(f"❌ Xato: {e}")
        return ConversationHandler.END
    return await after_login(update, context)

async def password_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    client = sessions.get(update.effective_user.id)
    try:
        await client.sign_in(password=update.message.text.strip())
    except Exception as e:
        await update.message.reply_text(f"❌ Xato: {e}")
        return ConversationHandler.END
    return await after_login(update, context)

async def after_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📊 Nechta guruh yaratilsin? (masalan 1-50)")
    return GROUP_RANGE

# ——— Guruh yaratish ———
async def background_group_creator(user_id, client, start, end, mode, context):
    created_channels = []
    for i in range(start, end + 1):
        if i > MAX_GROUPS:
            await context.bot.send_message(user_id, f"⚠ Maksimal limit {MAX_GROUPS} ga yetdi. Guruh yaratish to‘xtadi.")
            break
        try:
            result = await client(CreateChannelRequest(
                title=f"Guruh #{i}", about="Guruh sotiladi", megagroup=True
            ))
            channel = result.chats[0]
            created_channels.append(channel)
            try:
                await client(InviteToChannelRequest(channel, [TARGET_BOT]))
            except: pass
        except Exception as e:
            await context.bot.send_message(user_id, f"❌ Guruh #{i} yaratishda xato: {e}")

        # progress bar
        percent = int(len(created_channels)/ (end-start+1) * 100)
        await context.bot.send_message(user_id, f"⏳ {i-start+1}/{end-start+1} ({percent}%) yaratilmoqda...")
        await asyncio.sleep(1)

    progress[user_id] = end
    await context.bot.send_message(user_id, f"✅ Batch tugadi. {len(created_channels)} ta guruh yaratildi.")
    await client.disconnect()
    sessions.pop(user_id, None)

async def group_range_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        start, end = map(int, update.message.text.strip().split('-'))
        if start <= 0 or end < start:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Noto‘g‘ri format. Masalan: 1-50")
        return GROUP_RANGE

    client = sessions.get(update.effective_user.id)
    await update.message.reply_text("⏳ Guruh yaratish jarayoni boshlandi...")
    asyncio.create_task(background_group_creator(update.effective_user.id, client, start, end, context.user_data.get('mode'), context))
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Bekor qilindi.")
    if (client := sessions.pop(update.effective_user.id, None)):
        await client.disconnect()
    return ConversationHandler.END

# 🌐 Web server
async def handle(_):
    return web.Response(text="Bot alive!")

async def start_webserver():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    while True:
        await asyncio.sleep(3600)

# ——— Auto guruh (24h) ———
async def auto_group_task(context: ContextTypes.DEFAULT_TYPE):
    for user_id, client in sessions.items():
        last_group = progress.get(user_id, 0)
        start = last_group + 1
        end = min(start + 49, MAX_GROUPS)
        await background_group_creator(user_id, client, start, end, 'create_group', context)
        progress[user_id] = end

async def run_bot():
    application = Application.builder().token(bot_token).build()
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_password)],
            SELECT_MODE: [CallbackQueryHandler(mode_chosen)],
            PHONE: [MessageHandler(filters.TEXT | filters.CONTACT, phone_received)],
            CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, code_received)],
            PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, password_received)],
            GROUP_RANGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, group_range_received)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    application.add_handler(conv_handler)

    # Auto batch: har 24 soatda
    application.job_queue.run_repeating(auto_group_task, interval=86400, first=5)

    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    await asyncio.Event().wait()

async def main():
    await asyncio.gather(
        start_webserver(),
        run_bot()
    )

if __name__ == "__main__":
    asyncio.run(main())
