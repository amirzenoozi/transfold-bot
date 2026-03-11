import os
import logging
import re
import asyncio
import subprocess

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, InputMediaDocument
from telegram.ext import Application, PreCheckoutQueryHandler, CommandHandler, ContextTypes, MessageHandler, CallbackQueryHandler, MessageHandler, filters

from scripts import image_converters
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

MEDIA_GROUP_COOLDOWN = {}


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


# ---- Video Action Handlers ----
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
    status_msg = await update.message.reply_text("📥 **Downloading video...**", parse_mode = "Markdown")

    try:
        new_file = await context.bot.get_file(video.file_id)
        await new_file.download_to_drive(video_path)

        # Store the local path in user_data so button_handler can find it
        context.user_data['current_video_path'] = video_path

        # 5. Create the Inline Keyboard Menu
        keyboard = [
            [InlineKeyboardButton("🎵 Extract Audio (MP3)", callback_data='conv_mp3')],
            [InlineKeyboardButton("🎞️ Make GIF", callback_data='conv_gif')],
            [InlineKeyboardButton("✂️ Split Video", callback_data='conv_split')],
            [InlineKeyboardButton("🔘 Video to Round", callback_data='conv_round')],
            [InlineKeyboardButton("🔇 Remove Audio", callback_data='conv_mute')],
            [InlineKeyboardButton("🏷️ Add Watermark", callback_data='conv_watermark')],
            [InlineKeyboardButton("❌ Cancel", callback_data='cancel')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Remove the 'Downloading' message and show the menu
        await status_msg.delete()
        await update.message.reply_text(
            "**Transfold Menu**\nWhat would you like to do with this file?",
            reply_markup=reply_markup,
            parse_mode = "Markdown"
        )

    except Exception as e:
        logging.error(f"Download error for user {user_id}: {e}")
        await status_msg.edit_text("❌ Failed to download the file. Please try again.")
        # Cleanup if download failed halfway
        if os.path.exists(video_path):
            os.remove(video_path)


# ---- Image Action Handler ----
async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles incoming photos and documents (sent as images)."""
    # Photos in Telegram are sent as a list of sizes; we take the largest one
    message = update.message
    user_id = update.effective_user.id
    media_group_id = message.media_group_id

    photo = message.photo[-1] if message.photo else message.document
    if not photo: return

    user_dir = os.path.join(BASE_DOWNLOAD_PATH, str(user_id))
    os.makedirs(user_dir, exist_ok=True)

    # Generate path
    file_path = os.path.join(user_dir, f"{photo.file_id[:10]}.png")
    new_file = await context.bot.get_file(photo.file_id)
    await new_file.download_to_drive(file_path)

    # 2. Handle Media Groups (Galleries)
    if media_group_id:
        # Initialize the list for this group if it doesn't exist
        if 'media_groups' not in context.user_data:
            context.user_data['media_groups'] = {}

        if media_group_id not in context.user_data['media_groups']:
            context.user_data['media_groups'][media_group_id] = []

        context.user_data['media_groups'][media_group_id].append(file_path)

        # Wait a moment to see if more images are coming
        current_count = len(context.user_data['media_groups'][media_group_id])
        await asyncio.sleep(1.2)

        # If the count changed while we were sleeping, another instance of this
        # function is now the "latest" one. This one should exit.
        if len(context.user_data['media_groups'][media_group_id]) > current_count:
            return

    else:
        # Single image logic
        context.user_data['current_image_path'] = file_path
        context.user_data['media_groups'] = {}

    count = len(context.user_data['media_groups'].get(media_group_id, [])) if media_group_id else 1

    keyboard = [
        [InlineKeyboardButton("🖼️ Convert to JPEG", callback_data='img_to_jpg')],
        [InlineKeyboardButton("❌ Cancel", callback_data='img_cancel')]
    ]

    await update.message.reply_text(
        f"✅ {count} images received.\n"
        "Choose an action to apply to all:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


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
    image_actions = ['img_to_jpg', 'img_cancel']

    if data in about_and_profile_actions or data.startswith('pay_') or data.startswith('set_lang_'):
        await button_tap_handler(update, context)
    elif data in image_actions:
        await image_file_buttons_handler(update, context)
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

        elif action == 'conv_split':
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
            await query.message.reply_document(document=open(output_file, 'rb'))

        elif action == 'conv_mute':
            await query.edit_message_text("🔇 Muting video...")
            output_file = video_converters.remove_audio(video_path)

            await query.message.reply_video(
                video=open(output_file, 'rb'),
                caption="Audio removed! 🤐"
            )
            await query.delete_message()

        elif action == 'conv_watermark':
            await query.edit_message_text(
                "📝 **Watermark Mode**\n\n"
                "Please send the **Text** you want to add, or upload an **Image** file.\n"
                "I will place it in the bottom-right corner.",
                parse_mode="Markdown"
            )
            context.user_data['awaiting_watermark'] = True
            return

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


# ---- Image Files Button Handlers ----
async def image_file_buttons_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action = query.data
    media_groups = context.user_data.get('media_groups', {})
    image_paths = []

    if media_groups:
        # Get the first (and likely only) group
        group_id = list(media_groups.keys())[0]
        image_paths = media_groups[group_id]
    elif 'current_image_path' in context.user_data:
        image_paths = [context.user_data['current_image_path']]

    if not image_paths:
        await query.edit_message_text("❌ Session expired.")
        return

    output_files = []
    try:
        if action == 'img_to_jpg':
            await query.edit_message_text(f"📸 Converting {len(image_paths)} images...")

            for path in image_paths:
                output_path = image_converters.convert_to_jpeg(path)
                output_files.append(output_path)

            # Send back as a Gallery (Media Group)
            media_group = [InputMediaDocument(open(f, 'rb')) for f in output_files]
            await context.bot.send_media_group(chat_id=update.effective_chat.id, media=media_group)
            await query.delete_message()

    finally:
        # Cleanup ALL files
        for f in image_paths + output_files:
            if os.path.exists(f):
                os.remove(f)
        context.user_data.clear()


# ---- Handle All Waiting For messages ----
async def text_input_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Routes all text/media messages to the correct feature based on user state."""
    user_data = context.user_data

    # Priority 1: Check if user is adding a Watermark
    if user_data.get('awaiting_watermark'):
        await handle_watermark_input(update, context)
        return

    # Priority 2: Check if user is Splitting a video
    if user_data.get('awaiting_split_range'):
        if update.message.text:
            await handle_split_timestamp(update, context)
        else:
            await update.message.reply_text("❌ Please send the timestamp format (e.g., 00:10 - 00:20)")
        return

    # Priority 3: Fallback (User sent a message without picking a menu option)
    # If the bot isn't waiting for anything, we just ignore it or send help
    return


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


# ---- Get Watermark File / Text in the Second Phase ----
async def handle_watermark_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_watermark'):
        return

    video_path = context.user_data.get('current_video_path')
    user_id = update.effective_user.id
    output_file = None

    # 1. Check if it's Text
    if update.message.text:
        status = await update.message.reply_text("⚙️ Applying text watermark...")
        output_file = video_converters.add_text_watermark(video_path, update.message.text)

    # 2. Check if it's an Image (Photo or Document)
    elif update.message.photo or (update.message.document and update.message.document.mime_type.startswith('image/')):
        status = await update.message.reply_text("⚙️ Scaling and applying image watermark...")

        photo = update.message.photo[-1] if update.message.photo else update.message.document
        wm_path = os.path.join(BASE_DOWNLOAD_PATH, str(user_id), "temp_wm.png")

        file = await context.bot.get_file(photo.file_id)
        await file.download_to_drive(wm_path)

        output_file = video_converters.add_image_watermark(video_path, wm_path)
        if os.path.exists(wm_path): os.remove(wm_path)

    # 3. Invalid Input
    else:
        await update.message.reply_text("❌ We cannot use this as watermark, please send correct file (Text or Image).")
        return

    # 4. Success and Cleanup
    try:
        await update.message.reply_document(document=open(output_file, 'rb'), caption="Watermarked by Transfold! ✅")
        await status.delete()
    finally:
        if output_file and os.path.exists(output_file):
            os.remove(output_file)
        if video_path and os.path.exists(video_path):
            os.remove(video_path)
        context.user_data.clear()


# ---- Payment Handler ----
async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Answer the pre-checkout query to allow the payment to proceed."""
    query = update.pre_checkout_query
    await query.answer(ok=True)


async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirm to the user that the stars were received."""
    await update.message.reply_text("🌟 **Thank you for your support!**\nYour donation helps keep Transfold running fast and free.", parse_mode = "Markdown")

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
    application.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_image))
    application.add_handler(CallbackQueryHandler(main_callback_handler))

    application.add_handler(MessageHandler((filters.TEXT | filters.PHOTO | filters.Document.IMAGE) & ~filters.COMMAND, text_input_router))

    # Register the Payment Callbacks
    application.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))

    print("Bot is running...")
    application.run_polling()