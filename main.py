import asyncio
import json
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
import uvicorn
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery

ACCOUNTS_FILE = "accounts.json"
CONFIG_FILE = "config.json"

DEFAULT_CONFIG = {
    "message": "Hello everyone! This is an automated broadcast.",
    "delay": 60,
    "running": False
}

def load_json(filename, default):
    if os.path.exists(filename):
        try:
            with open(filename, "r") as f:
                return json.load(f)
        except Exception:
            return default
    return default

def save_json(filename, data):
    with open(filename, "w") as f:
        json.dump(data, f, indent=4)

config = load_json(CONFIG_FILE, DEFAULT_CONFIG)
accounts_data = load_json(ACCOUNTS_FILE, {})

broadcast_task = None

# Environment Variables se credentials fetch karna (Render ke liye zaroori hai)
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0")) # Apni Telegram ID yahan ya Render environment variable me dalein

bot = Client("master_control_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# FastAPI Lifespan to start and stop Telegram bot securely with web service
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await bot.start()
        print("Telegram Bot started successfully!")
    except Exception as e:
        print(f"Error starting bot: {e}")
    yield
    try:
        await bot.stop()
        print("Telegram Bot stopped.")
    except Exception:
        pass

app_fastapi = FastAPI(lifespan=lifespan)

@app_fastapi.get("/")
def home():
    return {"status": "Bot is running live on Render!"}

def get_main_keyboard():
    keyboard = [
        [InlineKeyboardButton("▶️ Start All", callback_data="start_broadcast"),
         InlineKeyboardButton("⏹️ Stop All", callback_data="stop_broadcast")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="settings_menu")],
        [InlineKeyboardButton("🔑 Session Login", callback_data="login_session"),
         InlineKeyboardButton("📱 Phone Login", callback_data="login_phone")],
        [InlineKeyboardButton("🗑️ Delete Account", callback_data="delete_account_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def check_admin(update):
    user_id = update.from_user.id
    return user_id == ADMIN_ID

@bot.on_message(filters.command("start"))
async def start_cmd(client, message: Message):
    if not await check_admin(message):
        await message.reply_text("❌ Aap is bot ke owner nahi hain! Is bot ko use karne ke liye owner (@G_KlNG) se access lein.")
        return

    accounts_count = len(accounts_data)
    running_status = "Running" if config["running"] else "Stopped"
    text = (
        f"✨ **Master Control Bot** ✨\n"
        f"👤 **User Panel**\n"
        f"📊 Accounts: {accounts_count} ({running_status})\n"
        f"⏱️ Delay Cycle: {config['delay']}s\n"
        f"💬 Message: {config['message'][:30]}..."
    )
    await message.reply_text(text, reply_markup=get_main_keyboard())

@bot.on_callback_query()
async def callback_handler(client, callback_query: CallbackQuery):
    if not await check_admin(callback_query):
        await callback_query.answer("❌ Access Denied! Owner se access lein.", show_alert=True)
        return

    data = callback_query.data
    
    if data == "start_broadcast":
        if config["running"]:
            await callback_query.answer("Bot is already running!", show_alert=True)
            return
        config["running"] = True
        save_json(CONFIG_FILE, config)
        global broadcast_task
        if broadcast_task is None or broadcast_task.done():
            broadcast_task = asyncio.create_task(run_broadcaster())
        await callback_query.answer("Broadcast Started Successfully!", show_alert=True)
        await update_panel(callback_query.message)

    elif data == "stop_broadcast":
        config["running"] = False
        save_json(CONFIG_FILE, config)
        await callback_query.answer("Broadcast Stopped!", show_alert=True)
        await update_panel(callback_query.message)

    elif data == "settings_menu":
        await callback_query.message.edit_text(
            f"⚙️ **Current Settings**\n\nDelay: {config['delay']} seconds\nMessage:\n`{config['message']}`\n\nTo change, use commands:\n`/setdelay [seconds]`\n`/setmsg [your message]`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="back_home")]])
        )

    elif data == "back_home":
        await update_panel(callback_query.message)
        
    elif data == "login_session":
        await callback_query.message.reply_text("Session Login ke liye apna Pyrogram String Session bhejein:\nFormat: `/addsession [string]`")
        await callback_query.answer()

    elif data == "login_phone":
        await callback_query.message.reply_text("Phone login ke liye number bhejein:\nFormat: `/login [phone_number]`")
        await callback_query.answer()

    elif data == "delete_account_menu":
        if not accounts_data:
            await callback_query.answer("No accounts logged in!", show_alert=True)
            return
        buttons = [[InlineKeyboardButton(f"Remove {info.get('phone', 'Account')}", callback_data=f"del_{sess}")] for sess, info in accounts_data.items()]
        buttons.append([InlineKeyboardButton("« Back", callback_data="back_home")])
        await callback_query.message.edit_text("Select an account to remove:", reply_markup=InlineKeyboardMarkup(buttons))

    elif data.startswith("del_"):
        sess_to_del = data.replace("del_", "")
        if sess_to_del in accounts_data:
            del accounts_data[sess_to_del]
            save_json(ACCOUNTS_FILE, accounts_data)
            await callback_query.answer("Account removed successfully!", show_alert=True)
            await update_panel(callback_query.message)

async def update_panel(message: Message):
    accounts_count = len(accounts_data)
    running_status = "Running" if config["running"] else "Stopped"
    text = (
        f"✨ **Master Control Bot** ✨\n"
        f"👤 **User Panel**\n"
        f"📊 Accounts: {accounts_count} ({running_status})\n"
        f"⏱️ Delay Cycle: {config['delay']}s\n"
        f"💬 Message: {config['message'][:30]}..."
    )
    try:
        await message.edit_text(text, reply_markup=get_main_keyboard())
    except Exception:
        pass

@bot.on_message(filters.command("setmsg"))
async def set_message_cmd(client, message: Message):
    if not await check_admin(message):
        return
    new_msg = message.text.partition(" ")[2]
    if not new_msg:
        await message.reply_text("Please provide a message. Example: `/setmsg Hello World`")
        return
    config["message"] = new_msg
    save_json(CONFIG_FILE, config)
    await message.reply_text("✅ Broadcast message updated successfully!")

@bot.on_message(filters.command("setdelay"))
async def set_delay_cmd(client, message: Message):
    if not await check_admin(message):
        return
    try:
        delay_val = int(message.text.partition(" ")[2])
        config["delay"] = delay_val
        save_json(CONFIG_FILE, config)
        await message.reply_text(f"✅ Delay updated to {delay_val} seconds!")
    except ValueError:
        await message.reply_text("Invalid format. Use `/setdelay 60`")

@bot.on_message(filters.command("addsession"))
async def add_session_cmd(client, message: Message):
    if not await check_admin(message):
        return
    parts = message.text.split(" ", 1)
    if len(parts) < 2:
        await message.reply_text("Usage: `/addsession [string_session]`")
        return
    session_str = parts[1].strip()
    try:
        temp_client = Client(name="temp_sess", api_id=API_ID, api_hash=API_HASH, session_string=session_str)
        await temp_client.start()
        me = await temp_client.get_me()
        await temp_client.stop()
        
        accounts_data[session_str] = {"phone": getattr(me, "phone_number", "Unknown")}
        save_json(ACCOUNTS_FILE, accounts_data)
        await message.reply_text(f"✅ Account added successfully for: {me.first_name} ({getattr(me, 'phone_number', '')})")
    except Exception as e:
        await message.reply_text(f"❌ Failed to login: {str(e)}")

async def run_broadcaster():
    while config["running"]:
        if not accounts_data:
            await asyncio.sleep(10)
            continue
        
        for session_str, info in list(accounts_data.items()):
            if not config["running"]:
                break
            try:
                user_client = Client(name=f"acc_{session_str[:10]}", api_id=API_ID, api_hash=API_HASH, session_string=session_str)
                await user_client.start()
                
                async for dialog in user_client.get_dialogs():
                    if dialog.chat.type in ["group", "supergroup"]:
                        try:
                            await user_client.send_message(dialog.chat.id, config["message"])
                            await asyncio.sleep(2)
                        except Exception:
                            continue
                await user_client.stop()
            except Exception as e:
                print(f"Error with session: {e}")
                
        delay_time = config.get("delay", 60)
        await asyncio.sleep(delay_time)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
