import os
import logging
import re
import subprocess

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import Application, PreCheckoutQueryHandler, CommandHandler, ContextTypes, MessageHandler, CallbackQueryHandler, MessageHandler, filters

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
        [InlineKeyboardButton(MESSAGES[lang]['contact_issue'], url="https://github.com/amirzenoozi/transfold-bot/issues/new")],
        [InlineKeyboardButton("💎 Donate with Telegram Stars", callback_data='show_donation_tiers')]
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
            [InlineKeyboardButton("🎵 Extract Audio (MP3)", callback_data='conv_mp3')],
            [InlineKeyboardButton("🎞️ Make GIF", callback_data='conv_gif')],
            [InlineKeyboardButton("✂️ Split Video", callback_data='request_split')],
            [InlineKeyboardButton("🔘 Video to Round", callback_data='conv_round')],
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


# ---- Profile Actions Handler ----
async def profile_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    lang = await get_lang(update, context)

    if query.data == "show_languages":
        # Merging logic: Replace Profile text with Language menu
        keyboard = [
            [InlineKeyboardButton("English 🇺🇸", callback_data="set_lang_en")],
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


# ---- Main CallBack Handler ----
async def main_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Routes inline button clicks to the correct handler based on callback_data."""
    query = update.callback_query
    data = query.data

    # List of button IDs that belong to Profile or About/Donation
    about_and_profile_actions = ['show_languages', 'back_to_profile', 'show_donation_tiers', 'back_to_about']

    if data in about_and_profile_actions or data.startswith('pay_') or data.startswith('set_lang_'):
        await button_tap_handler(update, context)
    else:
        await video_file_buttons_handler(update, context)


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

    elif data == 'show_donation_tiers':
        keyboard = [
            [InlineKeyboardButton("⭐️ 5 Stars", callback_data='pay_5'),
             InlineKeyboardButton("⭐️ 10 Stars", callback_data='pay_10')],
            [InlineKeyboardButton("⭐️ 25 Stars", callback_data='pay_25'),
             InlineKeyboardButton("⭐️ 50 Stars", callback_data='pay_50')],
            [InlineKeyboardButton("🔙 Back", callback_data='back_to_about')]
        ]
        await query.edit_message_text(
            "Select an amount to support the development of **Transfold**:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return

    elif data.startswith('pay_'):
        amount = int(query.data.split('_')[1])

        await context.bot.send_invoice(
            chat_id=update.effective_chat.id,
            title="Support Transfold",
            description=f"Donation of {amount} Telegram Stars. Thank you! 🚀",
            payload=f"donation_{amount}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice("Donation", amount)]
        )

    elif data == 'back_to_about':
        # Recreate the original About keyboard
        keyboard = [
            [
                InlineKeyboardButton(MESSAGES[lang]['contact_home_page'], url="https://amirdouzandeh.me/en"),
                InlineKeyboardButton(MESSAGES[lang]['contact_github'], url="https://github.com/amirzenoozi/transfold-bot")
            ],
            [InlineKeyboardButton(MESSAGES[lang]['contact_issue'], url="https://github.com/amirzenoozi/transfold-bot/issues/new")],
            [InlineKeyboardButton("💎 Donate with Telegram Stars", callback_data='show_donation_tiers')]
        ]

        await query.edit_message_text(
            MESSAGES[lang]['contact_message'],
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return

    elif data.startswith("set_lang_"):
        new_lang = query.data.split("_")[-1]
        database_manager.set_user_language(user_id, new_lang)
        context.user_data['lang'] = new_lang
        await query.message.edit_text(MESSAGES[new_lang]['lang_set'].format(lang=new_lang.upper()))


# ---- Video Files Button Handlers ----
async def video_file_buttons_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    await query.edit_message_text(f"Processing... {action.replace('conv_', '').upper()} ⚙️")

    output_file = None
    try:
        # EXECUTE CONVERSION BASED ON ACTION
        if action == 'conv_mp3':
            output_file = video_converters.video_to_mp3(video_path)
            await query.message.reply_document(document=open(output_file, 'rb'), filename="extracted_audio.mp3", caption="Here is your audio file! 🎵")

        elif action == 'conv_gif':
            output_file = video_converters.video_to_gif(video_path)
            await query.message.reply_animation(animation=open(output_file, 'rb'), caption="Transfold GIF")

        elif action == 'request_split':
            # Ask the user for the specific format
            await query.edit_message_text(
                "Please send the start and end time in this format: `2:10 - 3:40`\n"
                "Ensure start is >= 0 and end is within the video duration.",
                parse_mode="Markdown"
            )
            # Set a state so the next text message from this user is treated as a timestamp
            context.user_data['awaiting_split_range'] = True
            return

        elif action == 'conv_round':
            output_file = video_converters.video_to_round(video_path)
            await query.message.reply_video_note(video_note=open(output_file, 'rb'))

        await query.delete_message()

    except Exception as e:
        print(f"Conversion Error: {e}")
        await query.edit_message_text("❌ Conversion failed. The file might be corrupted.")

    finally:
        if not context.user_data.get('awaiting_split_range'):
            # CLEANUP: Always remove files to save space
            if video_path and os.path.exists(video_path):
                os.remove(video_path)
            if output_file and os.path.exists(output_file):
                os.remove(output_file)
            context.user_data.clear()


# ---- Split Video Using Start/End Timestamps ----
async def handle_split_timestamp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Only process if we are expecting a split range from this user
    if not context.user_data.get('awaiting_split_range'):
        return

    text = update.message.text
    video_path = context.user_data.get('current_video_path')
    output = None

    # Regex to match MM:SS - MM:SS or HH:MM:SS - HH:MM:SS
    pattern = r'^(\d{1,2}:?\d{0,2}:?\d{0,2})\s*-\s*(\d{1,2}:?\d{0,2}:?\d{0,2})$'
    match = re.match(pattern, text)

    if not match:
        await update.message.reply_text("❌ Invalid format. Please use: `2:10 - 3:40`")
        return

    start, end = match.groups()

    try:
        start_sec = utils.to_seconds(start)
        end_sec = utils.to_seconds(end)
        file_duration = video_converters.get_actual_video_duration(video_path)

        if start_sec < 0 or end_sec > file_duration or start_sec >= end_sec:
            await update.message.reply_text(f"❌ Limits error. Please stay between 0 and {int(file_duration)} seconds.")
            return

        # Execute Split
        status = await update.message.reply_text("✂️ Splitting video...")
        output = video_converters.split_video(video_path, start, end)

        await update.message.reply_document(document=open(output, 'rb'), filename="split_video.mp4")
        await status.delete()

    except Exception as e:
        await update.message.reply_text("❌ Failed to split. Ensure times are correct.")
    finally:
        # Cleanup
        if output and os.path.exists(output):
            os.remove(output)
        context.user_data['awaiting_split_range'] = False
        context.user_data.clear()
        # (Add your file removal logic here)


# ---- Payment Handler ----
async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Answer the pre-checkout query to allow the payment to proceed."""
    query = update.pre_checkout_query
    await query.answer(ok=True)


async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirm to the user that the stars were received."""
    await update.message.reply_text("🌟 **Thank you for your support!**\nYour donation helps keep Transfold running fast and free.")

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
    application.add_handler(CallbackQueryHandler(main_callback_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_split_timestamp))

    # Register the Payment Callbacks
    application.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))

    print("Bot is running...")
    application.run_polling()