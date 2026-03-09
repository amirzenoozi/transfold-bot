import os
import subprocess
import logging
from os import utime

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, CallbackQueryHandler, MessageHandler, filters

from scripts import video_converters
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
    video = update.message.video or update.message.document
    user_id = update.effective_user.id
    if not video: return

    # Check size as before
    if video.file_size > utils.convert_mb_to_bytes(MAX_VIDEO_FILE_SIZE_MB):
        await update.message.reply_text("File too large!")
        return

    # 3. Setup the user-specific directory
    user_dir = os.path.join(BASE_DOWNLOAD_PATH, str(user_id))
    if not os.path.exists(user_dir):
        os.makedirs(user_dir, exist_ok=True)

    # Create a unique path for the input file
    # We use part of the file_id to ensure uniqueness
    video_path = os.path.join(user_dir, f"input_{video.file_id[:10]}.mp4")

    # 4. Inform the user and Download
    status_msg = await update.message.reply_text("📥 **Downloading video...**")

    try:
        new_file = await context.bot.get_file(video.file_id)
        await new_file.download_to_drive(video_path)

        # Store the local path in user_data so button_handler can find it
        context.user_data['current_video_path'] = video_path

        # 5. Create the Inline Keyboard Menu
        keyboard = [
            [
                InlineKeyboardButton("🎵 Extract Audio (MP3)", callback_data='conv_mp3'),
                InlineKeyboardButton("🎞️ Make GIF", callback_data='conv_gif')
            ],
            [InlineKeyboardButton("❌ Cancel", callback_data='cancel')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Remove the 'Downloading' message and show the menu
        await status_msg.delete()
        await update.message.reply_text(
            "**Transfold Menu**\nWhat would you like to do with this file?",
            reply_markup=reply_markup
        )

    except Exception as e:
        logging.error(f"Download error for user {user_id}: {e}")
        await status_msg.edit_text("❌ Failed to download the file. Please try again.")
        # Cleanup if download failed halfway
        if os.path.exists(video_path):
            os.remove(video_path)


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


# ---- Profile Button Handlers ----
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


# ---- Video Files Button Handlers ----
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action = query.data
    video_path = context.user_data.get('current_video_path')  # Store path instead of just ID

    if action == 'cancel':
        # Clean up the original video if they cancel
        if video_path and os.path.exists(video_path):
            os.remove(video_path)
        await query.edit_message_text("Task cancelled. Original file deleted.")
        return

    if not video_path or not os.path.exists(video_path):
        await query.edit_message_text("Error: File not found. Please resend the video.")
        return

    processing_msg = await query.edit_message_text(f"Processing... {action.replace('conv_', '').upper()} ⚙️")

    output_file = None
    try:
        # EXECUTE CONVERSION BASED ON ACTION
        if action == 'conv_mp3':
            output_file = video_converters.video_to_mp3(video_path)
            await query.message.reply_document(audio=open(output_file, 'rb'), filename="extracted_audio.mp3", caption="Here is your audio file! 🎵")

        elif action == 'conv_gif':
            output_file = video_converters.video_to_gif(video_path)
            await query.message.reply_animation(animation=open(output_file, 'rb'), caption="Transfold GIF")

        await processing_msg.delete()
        await query.delete_message()

    except Exception as e:
        print(f"Conversion Error: {e}")
        await query.edit_message_text("❌ Conversion failed. The file might be corrupted.")

    finally:
        # CLEANUP: Always remove files to save space
        if video_path and os.path.exists(video_path):
            os.remove(video_path)
        if output_file and os.path.exists(output_file):
            os.remove(output_file)
        context.user_data.clear()


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
    application.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))
    application.add_handler(CallbackQueryHandler(button_handler))

    print("Bot is running...")
    application.run_polling()