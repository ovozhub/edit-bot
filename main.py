import os
import logging
import asyncio
from aiohttp import web
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.tl.functions.channels import CreateChannelRequest, InviteToChannelRequest
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# === Logging ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === States ===
ASK_PASSWORD, SELECT_MODE, PHONE, CODE, PASSWORD, GROUP_RANGE = range(6)

# === Data ===
sessions = {}
bot_token = os.environ.get("BOT_TOKEN", "8350150569:AAEfax1UQn1AnpWrDdwFo0c7zCzDklkcbJk")
api_id = int(os.environ.get("API_ID", "25351311"))
api_hash = os.environ.get("API_HASH", "7b854af9996797aa9ca67b42f1cd5cbe")
admin_password = os.environ.get("ADMIN_PASSWORD", "KOT")

# === Web server ===
async def handle(request):
    return web.Response(text="Bot is running!")

async def start_webserver():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"🌐 Web-server {port} portda ishga tushdi.")

# === Bot Handlers ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔑 Parolni kiriting:")
    return ASK_PASSWORD

async def ask_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == admin_password:
        buttons = [[
            InlineKeyboardButton("📱 Oddiy login", callback_data="normal"),
            InlineKeyboardButton("👥 Guruh yaratish", callback_data="group"),
        ]]
        await update.message.reply_text("Mode tanlang:", reply_markup=InlineKeyboardMarkup(buttons))
        return SELECT_MODE
    else:
        await update.message.reply_text("❌ Noto‘g‘ri parol.")
        return ConversationHandler.END

async def mode_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["mode"] = query.data
    await query.edit_message_text("📞 Telefon raqamni yuboring:")
    return PHONE

async def phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text
    context.user_data["phone"] = phone
    client = TelegramClient(f"sessions/{update.message.from_user.id}", api_id, api_hash)
    await client.connect()
    sessions[update.message.from_user.id] = client

    if not await client.is_user_authorized():
        try:
            await client.send_code_request(phone)
            await update.message.reply_text("📩 Kod yuborildi. Iltimos kiriting:")
            return CODE
        except Exception as e:
            logger.exception(e)
            await update.message.reply_text(f"❌ Xato: {e}")
            return ConversationHandler.END
    else:
        await update.message.reply_text("✅ Avvaldan login qilingan!")
        return ConversationHandler.END

async def code_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text
    client = sessions[update.message.from_user.id]
    phone = context.user_data["phone"]
    try:
        await client.sign_in(phone=phone, code=code)
        if context.user_data["mode"] == "group":
            await update.message.reply_text("Nechta guruh yaratay?")
            return GROUP_RANGE
        else:
            await update.message.reply_text("✅ Login muvaffaqiyatli.")
            return ConversationHandler.END
    except SessionPasswordNeededError:
        await update.message.reply_text("🔐 2FA parolni kiriting:")
        return PASSWORD
    except Exception as e:
        logger.exception(e)
        await update.message.reply_text(f"❌ Xato: {e}")
        return ConversationHandler.END

async def password_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    client = sessions[update.message.from_user.id]
    phone = context.user_data["phone"]
    try:
        await client.sign_in(phone=phone, password=update.message.text)
        await update.message.reply_text("✅ 2FA muvaffaqiyatli!")
        return ConversationHandler.END
    except Exception as e:
        logger.exception(e)
        await update.message.reply_text(f"❌ Xato: {e}")
        return ConversationHandler.END

async def group_range_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count = int(update.message.text)
    client = sessions[update.message.from_user.id]

    for i in range(count):
        try:
            result = await client(CreateChannelRequest(
                title=f"Guruh {i+1}",
                about="Auto-created group",
                megagroup=True
            ))
            chat = result.chats[0]
            await client(InviteToChannelRequest(chat, [await client.get_me()]))
        except Exception as e:
            logger.exception(e)

    await update.message.reply_text(f"✅ {count} ta guruh yaratildi.")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Bekor qilindi.")
    return ConversationHandler.END

# === Main ===
if __name__ == "__main__":
    # Web serverni background task qilib ishga tushuramiz
    asyncio.get_event_loop().create_task(start_webserver())

    application = Application.builder().token(bot_token).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_password)],
            SELECT_MODE: [CallbackQueryHandler(mode_chosen)],
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, phone_received)],
            CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, code_received)],
            PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, password_received)],
            GROUP_RANGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, group_range_received)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    application.add_handler(conv_handler)

    logger.info("🤖 Bot ishga tushdi.")
    application.run_polling()  # ✅ async emas, to‘g‘ridan-to‘g‘ri
