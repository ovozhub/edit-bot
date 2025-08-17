import logging
import asyncio
import os
from pathlib import Path
from aiohttp import web

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ConversationHandler, MessageHandler, filters, ContextTypes
from telethon import TelegramClient
from telethon.tl.functions.channels import CreateChannelRequest, InviteToChannelRequest

# 📂 sessions papkasini yaratamiz
Path("sessions").mkdir(exist_ok=True)

# ——— TELEGRAM API ma’lumotlari ———
api_id = 25351311
api_hash = "7b854af9996797aa9ca67b42f1cd5cbe"
bot_token = "8350150569:AAEfax1UQn1AnpWrDdwFo0c7zCzDklkcbJk"

# 🔑 Kirish paroli
ACCESS_PASSWORD = "dnx"

# 🎯 Avtomatik qo‘shiladigan bot
TARGET_BOT = "@oxang_bot"

# ——— LOGGER ———
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ——— Holatlar ———
ASK_PASSWORD, SELECT_MODE, PHONE, CODE, PASSWORD, GROUP_RANGE = range(6)

# ——— Session va avtorizatsiya boshqaruvlari ———
sessions = {}
authorized_users = set()
progress_messages = {}  # foiz xabarlarini saqlash

# ——— START ———
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id in authorized_users:
        return await show_menu(update)
    await update.message.reply_text("🔒 Kirish parolini kiriting:")
    return ASK_PASSWORD

# ——— Parol tekshirish ———
async def ask_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip() != ACCESS_PASSWORD:
        await update.message.reply_text("❌ Noto‘g‘ri parol.")
        return ConversationHandler.END
    authorized_users.add(update.effective_user.id)
    return await show_menu(update)

# ——— Menyu chiqarish ———
async def show_menu(update: Update):
    keyboard = [[InlineKeyboardButton("Guruh ochish", callback_data='create_group')]]
    target = update.message or update.callback_query.message
    await target.reply_text("Rejimni tanlang⚙️", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT_MODE

# ——— Rejim tanlash ———
async def mode_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['mode'] = query.data
    keyboard = ReplyKeyboardMarkup([[KeyboardButton("📱 Telefon raqamni yuborish", request_contact=True)]], resize_keyboard=True, one_time_keyboard=True)
    await query.message.reply_text("📞 Telefon raqamingizni yuboring:", reply_markup=keyboard)
    return PHONE

# ——— Telefon qabul qilish ———
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
        await client.send_code_request(phone)
        await update.message.reply_text("📩 Kod yuborildi, kiriting:")
        return CODE
    await update.message.reply_text("✅ Akkount allaqachon ulangan.")
    return await after_login(update, context)

# ——— Kod qabul qilish ———
async def code_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    client = sessions.get(update.effective_user.id)
    phone = context.user_data.get('phone')
    try:
        await client.sign_in(phone, update.message.text.strip())
    except Exception as e:
        await update.message.reply_text(f"❌ Xato: {e}")
        return ConversationHandler.END
    return await after_login(update, context)

# ——— Login tugagach ———
async def after_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📊 Nechta guruh yaratilsin? (masalan 1-50)")
    return GROUP_RANGE

# ——— Guruh yaratish jarayoni (progress bar bilan) ———
async def background_group_creator(user_id, client, start, end, context):
    total = end - start + 1
    msg = await context.bot.send_message(user_id, f"⏳ {start}-{end} gacha guruhlar yaratilmoqda...\n\n[░░░░░░░░░░░░░░░░░░░░] 0%")
    for i in range(start, end + 1):
        try:
            result = await client(CreateChannelRequest(title=f"Guruh #{i}", about="Guruh sotiladi", megagroup=True))
            channel = result.chats[0]
            try:
                await client(InviteToChannelRequest(channel, [TARGET_BOT]))
            except:
                pass
        except:
            pass

        # progress bar
        percent = int(((i - start + 1) / total) * 100)
        filled = int(percent / 5)
        bar = "█" * filled + "░" * (20 - filled)
        await msg.edit_text(f"⏳ {start}-{end} gacha guruhlar yaratilmoqda...\n\n{bar} {percent}%")
        await asyncio.sleep(0.5)  # demo uchun 0.5s

    await msg.edit_text(f"✅ {total} ta guruh yaratildi!")
    await client.disconnect()
    sessions.pop(user_id, None)

# ——— Guruhlar soni qabul qilish ———
async def group_range_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        start, end = map(int, update.message.text.strip().split('-'))
        if start <= 0 or end < start:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Noto‘g‘ri format. Masalan: 1-50")
        return GROUP_RANGE

    client = sessions.get(update.effective_user.id)
    asyncio.create_task(background_group_creator(update.effective_user.id, client, start, end, context))
    return ConversationHandler.END

# ——— Bekor qilish ———
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Bekor qilindi.")
    if (client := sessions.pop(update.effective_user.id, None)):
        await client.disconnect()
    return ConversationHandler.END

# ——— WEB SERVER ———
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
    logger.info(f"🌐 Web-server {port} portda ishga tushdi.")
    while True:
        await asyncio.sleep(3600)

# ——— Avto-guruh yaratish (demo 5 daqiqa) ———
async def auto_group_task(context):
    for user_id, client in list(sessions.items()):
        # oldingi limitni aniqlash va keyingi guruhlarni avtomatik yaratish mumkin
        # demo uchun 1-5 gacha
        asyncio.create_task(background_group_creator(user_id, client, 1, 5, context))

# ——— BOTNI ISHGA TUSHIRISH ———
async def run_bot():
    application = Application.builder().token(bot_token).build()
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_password)],
            SELECT_MODE: [CallbackQueryHandler(mode_chosen)],
            PHONE: [MessageHandler(filters.TEXT | filters.CONTACT, phone_received)],
            CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, code_received)],
            PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, code_received)],
            GROUP_RANGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, group_range_received)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    application.add_handler(conv_handler)

    logger.info("🤖 Bot ishga tushdi.")

    # demo uchun avto-guruhni 5 daqiqadan keyin ishga tushiramiz
    async def periodic():
        while True:
            await auto_group_task(application)
            await asyncio.sleep(300)  # 5 daqiqa
    asyncio.create_task(periodic())

    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    await asyncio.Event().wait()

# ——— ASOSIY ———
async def main():
    await asyncio.gather(
        start_webserver(),
        run_bot()
    )

if __name__ == "__main__":
    asyncio.run(main())
