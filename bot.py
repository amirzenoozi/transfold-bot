import os
import subprocess
import logging
from os import utime

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from scripts import database_manager
from scripts import utils

# Enable logging to see errors in the console
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Load environment variables
load_dotenv()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ADMIN_ID = os.getenv('ADMIN_ID')

MAX_VIDEO_FILE_SIZE_MB = os.getenv('MAX_VIDEO_FILE_SIZE_MB', 20)
BASE_DOWNLOAD_PATH = os.path.join(BASE_DIR, "downloads")

# --- Localization Data ---
LOCALES_PATH = os.path.join(BASE_DIR, "locales")
SUPPORTED_LANGUAGES = ['en']
MESSAGES = utils.load_all_locales(LOCALES_PATH, SUPPORTED_LANGUAGES)


# ---- Commands ----
async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Initial Profile message with Inline Buttons."""
    user_id = update.effective_user.id
    lang = await get_lang(update, context)

    # Fetch current settings to show the user
    user_info = database_manager.get_user_info(user_id)

    text = MESSAGES[lang]['profile']['first_step'].format(lang=lang.upper())

    keyboard = [
        [InlineKeyboardButton(MESSAGES[lang]['profile']['change_lng_btn'], callback_data="show_languages")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")


async def profile_command_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Helper function to refresh the profile view by editing the current message.
    Used when returning from sub-menus like Language selection.
    """
    query = update.callback_query
    user_id = update.effective_user.id
    lang = context.user_data.get('lang') or database_manager.get_user_language(user_id) or 'en'

    text = MESSAGES[lang]['profile']['first_step'].format(lang=lang.upper())

    keyboard = [
        [InlineKeyboardButton(MESSAGES[lang]['profile']['change_lng_btn'], callback_data="show_languages")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # 4. Use edit_message_text instead of reply_text
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /home command to show project links."""
    lang = await get_lang(update, context)
    text = MESSAGES[lang]['contact_message']
    keyboard = [
        [
            InlineKeyboardButton(MESSAGES[lang]['contact_home_page'], url="https://amirdouzandeh.me/en"),
            InlineKeyboardButton(MESSAGES[lang]['contact_github'], url="https://github.com/amirzenoozi/transfold-bot")
        ],
        [
            InlineKeyboardButton(MESSAGES[lang]['contact_issue'], url="https://github.com/amirzenoozi/transfold-bot/issues/new")
        ]
    ]

    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


# ---- Action Handlers ----
async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Get the video or document object
    video = update.message.video or update.message.document
    user_id = update.message.from_user.id

    if not video:
        return

    # 1. Check file size before downloading
    if video.file_size > utils.convert_mb_to_bytes(MAX_VIDEO_FILE_SIZE_MB):
        size_in_mb = round(video.file_size / (1024 * 1024), 2)
        await update.message.reply_text(
            f"❌ **File too large!**\n\nYour file is **{size_in_mb} MB**. "
            f"The limit is **{MAX_VIDEO_FILE_SIZE_MB} MB**."
        )
        return

    # 2. Setup user-specific directory
    # Path: downloads/12345678/
    user_dir = os.path.join(BASE_DOWNLOAD_PATH, str(user_id))
    if not os.path.exists(user_dir):
        os.makedirs(user_dir)

    # Define file paths inside the user folder
    video_path = os.path.join(user_dir, f"video_{video.file_id[:10]}.mp4")
    audio_path = os.path.join(user_dir, f"audio_{video.file_id[:10]}.mp3")

    status_msg = await update.message.reply_text("Loading... ⏳")

    try:
        # 3. Download the file
        new_file = await context.bot.get_file(video.file_id)
        await new_file.download_to_drive(video_path)

        # 4. Extract Audio using FFmpeg
        # -vn: no video, -q:a 2: high quality VBR
        cmd = [
            "ffmpeg", "-i", video_path,
            "-vn", "-ar", "44100", "-ac", "2", "-b:a", "192k",
            audio_path, "-y"
        ]
        subprocess.run(cmd, check=True)

        # 5. Send audio back
        await update.message.reply_audio(
            audio=open(audio_path, 'rb'),
            title="Your Audio file",
            filename="audio.mp3"
        )
        await status_msg.delete()

    except Exception as e:
        logging.error(f"Error for user {user_id}: {e}")
        await update.message.reply_text("Sorry, an error occurred during transmutation.")

    # # 6. Cleanup - remove files after processing
    # finally:
    #     if os.path.exists(video_path):
    #         os.remove(video_path)
    #     if os.path.exists(audio_path):
    #         os.remove(audio_path)


# --- Profile Actions Handler ---
async def profile_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    lang = await get_lang(update, context)

    if query.data == "show_languages":
        # Merging logic: Replace Profile text with Language menu
        keyboard = [
            [InlineKeyboardButton("English 🇺🇸", callback_data="set_lang_en"),
             InlineKeyboardButton("Italiano 🇮🇹", callback_data="set_lang_it")],
            [InlineKeyboardButton("Русский 🇷🇺", callback_data="set_lang_ru"),
             InlineKeyboardButton("Deutsch 🇩🇪", callback_data="set_lang_de")],
            [InlineKeyboardButton(MESSAGES[lang]['profile']['back_to_profile'], callback_data="back_to_profile")]
        ]
        await query.edit_message_text(
            MESSAGES[context.user_data.get('lang', 'en')]['choose_lang'],
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data == "back_to_profile":
        # Returns user to the main profile view
        # Use a shortcut: call the command logic but edit the message instead of replying
        # You can refactor the profile text generation into a helper to avoid duplication
        await profile_command_edit(update, context)


# ---- Callbacks Handlers ----
async def button_tap_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    data = query.data
    await query.answer()

    lang = await get_lang(update, context)

    if data == "show_languages":
        keyboard = [[
            InlineKeyboardButton("English 🇺🇸", callback_data="set_lang_en"),
        ]]
        await query.message.edit_text(MESSAGES[lang]['choose_lang'], reply_markup=InlineKeyboardMarkup(keyboard))


    elif query.data.startswith("set_lang_"):
        new_lang = query.data.split("_")[-1]
        database_manager.set_user_language(user_id, new_lang)
        context.user_data['lang'] = new_lang
        await query.message.edit_text(MESSAGES[new_lang]['lang_set'].format(lang=new_lang.upper()))


# ---- Helpers ----
async def get_lang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Gets language from RAM cache, or DB if not present."""
    user_id = update.effective_user.id
    if 'lang' not in context.user_data:
        # Fallback to DB and store in RAM
        lang = database_manager.get_user_language(user_id)
        context.user_data['lang'] = lang
    return context.user_data['lang']



if __name__ == '__main__':
    if not TOKEN:
        print("CRITICAL ERROR: TELEGRAM_BOT_TOKEN not found.")
        exit(1)

    # Initialize the database table
    database_manager.init_db()

    # Build the application
    application = Application.builder().token(TOKEN).build()

    # Command Handlers
    application.add_handler(CommandHandler("profile", profile_command))
    application.add_handler(CommandHandler("about", about_command))

    # Handler for videos and documents (in case video is sent as an uncompressed file)
    video_handler = MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video)
    application.add_handler(video_handler)

    print("Bot is running...")
    application.run_polling()