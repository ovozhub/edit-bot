import logging
import os
from pathlib import Path
from aiohttp import web

from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup, Update,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters, ContextTypes
)
from telethon import TelegramClient, errors
from telethon.tl.functions.channels import CreateChannelRequest, InviteToChannelRequest

# 📂 sessions papkasini yaratamiz
Path("sessions").mkdir(exist_ok=True)

# ——— TELEGRAM API ma’lumotlari ———
api_id = 25351311
api_hash = "7b854af9996797aa9ca67b42f1cd5cbe"
bot_token = "8350150569:AAEfax1UQn1AnpWrDdwFo0c7zCzDklkcbJk"  # ⚠️ o'z tokeningizni qo'ying

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
    keyboard = [[
        InlineKeyboardButton("Guruh ochish", callback_data='create_group'),
        InlineKeyboardButton("Guruhni topshirish", callback_data='transfer_group')
    ]]
    target = update.message or update.callback_query.message
    await target.reply_text("Rejimni tanlang⚙️", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT_MODE


# ——— Rejim tanlash ———
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


# ——— Telefon qabul qilish ———
async def phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.contact.phone_number if update.message.contact else update.message.text.strip()
    if not phone.startswith('+') or not phone[1:].isdigit():
        await update.message.reply_text("Telefon raqam + bilan boshlanishi va raqam bo‘lishi kerak.")
        return PHONE

    context.user_data['phone'] = phone
    client = TelegramClient(f"sessions/{phone}", api_id, api_hash)
    sessions[update.effective_user.id] = client

    await client.start(phone=lambda: phone)
    if not await client.is_user_authorized():
        try:
            await client.send_code_request(phone)
            await update.message.reply_text("📩 Kod yuborildi, kiriting:")
            return CODE
        except Exception as e:
            logger.exception(e)
            await update.message.reply_text(f"❌ Xato: {e}")
            return ConversationHandler.END

    await update.message.reply_text("✅ Akkount allaqachon ulangan.")
    return await after_login(update, context)


# ——— Kod qabul qilish ———
async def code_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    client = sessions.get(update.effective_user.id)
    phone = context.user_data.get('phone')
    try:
        await client.sign_in(phone, update.message.text.strip())
    except errors.SessionPasswordNeededError:
        await update.message.reply_text("🔑 2 bosqichli parolni kiriting:")
        return PASSWORD
    except Exception as e:
        logger.exception(e)
        await update.message.reply_text(f"❌ Xato: {e}")
        return ConversationHandler.END
    return await after_login(update, context)


# ——— 2FA parol ———
async def password_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    client = sessions.get(update.effective_user.id)
    try:
        await client.sign_in(password=update.message.text.strip())
    except Exception as e:
        logger.exception(e)
        await update.message.reply_text(f"❌ Xato: {e}")
        return ConversationHandler.END
    return await after_login(update, context)


# ——— Login tugagach ———
async def after_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📊 Nechta guruh yaratilsin? (masalan 1-5)")
    return GROUP_RANGE


# ——— Guruh yaratish jarayoni ———
async def background_group_creator(user_id, client, start, end, mode, context):
    created, failed = 0, 0
    status_msg = await context.bot.send_message(user_id, f"⏳ 0/{end-start+1} guruh yaratildi...")

    for i in range(start, end + 1):
        try:
            result = await client(CreateChannelRequest(
                title=f"Guruh #{i}", about="Guruh sotiladi", megagroup=True
            ))
            channel = result.chats[0]
            created += 1
            try:
                await client(InviteToChannelRequest(channel, [TARGET_BOT]))
            except Exception:
                pass
        except Exception:
            failed += 1

        try:
            await status_msg.edit_text(
                f"⏳ Jarayon: {i}/{end-start+1}\n"
                f"✅ Muvaffaqiyatli: {created}\n"
                f"❌ Nosoz: {failed}"
            )
        except Exception:
            pass

    await context.bot.send_message(user_id, f"🏁 Tugadi!\n✅ {created} ta yaratildi\n❌ {failed} ta xato")
    await client.disconnect()
    sessions.pop(user_id, None)


# ——— Guruhlar soni qabul qilish ———
async def group_range_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        start, end = map(int, update.message.text.strip().split('-'))
        if start <= 0 or end < start:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Noto‘g‘ri format. Masalan: 1-5")
        return GROUP_RANGE

    client = sessions.get(update.effective_user.id)
    await update.message.reply_text("⏳ Guruh yaratish jarayoni boshlandi...")
    await background_group_creator(
        update.effective_user.id, client, start, end,
        context.user_data.get('mode'), context
    )
    return ConversationHandler.END


# ——— Bekor qilish ———
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Bekor qilindi.")
    if (client := sessions.pop(update.effective_user.id, None)):
        await client.disconnect()
    return ConversationHandler.END


# 🌐 WEB SERVER + BOT
async def main():
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

    # webhook URL (Render domeningizni qo‘ying)
    PORT = int(os.environ.get("PORT", 8080))
    WEBHOOK_URL = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME')}/"

    logger.info(f"🤖 Bot webhook rejimida ishga tushdi: {WEBHOOK_URL}")

    await application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=bot_token,
        webhook_url=WEBHOOK_URL + bot_token,
    )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
