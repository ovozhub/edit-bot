import asyncio
from telethon import TelegramClient, errors
from telegram import Bot
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ConversationHandler

# ================== SOZLAMALAR ==================
API_ID = 25351311
API_HASH = '7b854af9996797aa9ca67b42f1cd5cbe'
BOT_TOKEN = '8350150569:AAEfax1UQn1AnpWrDdwFo0c7zCzDklkcbJk'

# Demo uchun 5 daqiqa (300s), haqiqiyda 24*60*60
AUTO_INTERVAL = 300
MAX_GROUPS = 500

# ================== GLOBAL ==================
group_counter = 0
sessions = {}  # raqam: client
progress_message = {}  # chat_id: message object

# ================== TELETHON CLIENT ==================
async def login_number(phone):
    client = TelegramClient(f"sessions/{phone}", API_ID, API_HASH)
    await client.start(phone)
    sessions[phone] = client
    return client

# ================== GROUP YARATISH ==================
async def create_groups(client, start, end, chat_id, bot):
    global group_counter
    total = end - start + 1
    msg = await bot.send_message(chat_id, f"⏳ {start}-{end} gacha guruhlar yaratilmoqda...")
    for i in range(total):
        if group_counter >= MAX_GROUPS:
            await msg.edit_text(f"⚠ Maksimal {MAX_GROUPS} guruhga yetildi. Yaratish to‘xtadi.")
            return
        group_counter += 1
        # Guruh yaratish
        try:
            await client(functions.messages.CreateChatRequest(
                users=[],
                title=f"ShadowFORCE {group_counter}"
            ))
        except errors.FloodWaitError as e:
            await asyncio.sleep(e.seconds)
        # Progress bar
        percent = int((i + 1) / total * 100)
        filled = int(percent / 5)
        bar = "█" * filled + "░" * (20 - filled)
        await msg.edit_text(f"⏳ {start}-{end} gacha guruhlar yaratilmoqda...\n\n{bar} {percent}%")
        await asyncio.sleep(2)
    await msg.edit_text(f"✅ {start}-{end} gacha guruhlar yaratildi!")

# ================== AVTO-GURUH ==================
async def auto_group_task():
    for phone, client in sessions.items():
        start = group_counter + 1
        end = min(group_counter + 50, MAX_GROUPS)
        if start > MAX_GROUPS:
            continue
        bot = Bot(token=BOT_TOKEN)
        await create_groups(client, start, end, chat_id=123456789, bot=bot)  # chat_id o‘zgartiriladi

# ================== TELEGRAM BOT ==================
async def start(update, context):
    await update.message.reply_text("🤖 Bot ishga tushdi.")

async def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    
    # Demo uchun 5 daqiqa, haqiqiy 86400
    application.job_queue.run_repeating(lambda ctx: asyncio.create_task(auto_group_task()),
                                        interval=AUTO_INTERVAL,
                                        first=5)
    
    await application.start()
    await application.updater.start_polling()
    await application.wait_closed()

if __name__ == "__main__":
    asyncio.run(main())
