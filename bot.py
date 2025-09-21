import os
import logging
import yt_dlp
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Your secret Telegram Bot Token
TELEGRAM_TOKEN = "7211938478:AAFIZ9GTet7K7vr_QnnQaP9Gf-6s4hOHSvA" 

# Telegram's maximum file size for bots is 50 MB
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024

def format_bytes(size):
    """Converts bytes to a human-readable format."""
    if size is None:
        return "N/A"
    power = 1024
    n = 0
    power_labels = {0: '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
    while size > power and n < len(power_labels) -1 :
        size /= power
        n += 1
    return f"{size:.1f}{power_labels[n]}B"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a welcome message."""
    await update.message.reply_text(
        "👋 Hi! Send me a video link. I'll show you the available download options."
    )

async def url_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles a URL, fetches video info, and shows format buttons."""
    url = update.message.text
    processing_msg = await update.message.reply_text("🔎 Fetching video info...")

    ydl_opts = {'quiet': True, 'noplaylist': True}
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        logger.error(f"Error fetching info for {url}: {e}")
        await processing_msg.edit_text("❌ Could not process this URL. It might be unsupported, private, or invalid.")
        return

    keyboard = []
    # Filter and sort formats: prioritize mp4, then by resolution
    formats = sorted(
        [f for f in info.get('formats', []) if f.get('vcodec') != 'none' and f.get('acodec') != 'none' and f.get('ext') == 'mp4'],
        key=lambda f: f.get('height', 0) or 0,
        reverse=True
    )
    
    # Limit to a reasonable number of buttons
    MAX_BUTTONS = 10 
    for f in formats[:MAX_BUTTONS]:
        format_id = f.get('format_id')
        resolution = f.get('format_note') or f"{f.get('height')}p"
        filesize = f.get('filesize') or f.get('filesize_approx')
        filesize_str = format_bytes(filesize)
        
        button_text = f"{f.get('ext')} - {resolution} ({filesize_str})"
        
        # Callback data must be a string. We pack necessary info here.
        callback_data = json.dumps({'id': format_id, 'url': url, 'ext': f.get('ext')})
        
        # Telegram has a 64-byte limit on callback_data, check it.
        if len(callback_data.encode('utf-8')) > 64:
            logger.warning(f"Callback data too long for format {format_id}")
            continue

        keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])

    if not keyboard:
        await processing_msg.edit_text("❌ No downloadable MP4 versions found.")
        return

    reply_markup = InlineKeyboardMarkup(keyboard)
    thumbnail_url = info.get('thumbnail')
    
    await processing_msg.delete()
    if thumbnail_url:
        await update.message.reply_photo(
            photo=thumbnail_url,
            caption=f"🎬 **{info.get('title')}**\n\nSelect a version to download:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            f"🎬 **{info.get('title')}**\n\nSelect a version to download:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the user's button click to download a specific format."""
    query = update.callback_query
    await query.answer() # Acknowledge the button press

    try:
        data = json.loads(query.data)
        format_id = data['id']
        url = data['url']
        ext = data['ext']
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"Error decoding callback data: {e}")
        await query.edit_message_caption(caption="❌ An error occurred. Please try again.")
        return

    # Update the message to show progress
    await query.edit_message_caption(caption="Downloading to server... 📥")

    output_template = f'%(id)s_{format_id}.{ext}'
    ydl_opts = {
        'format': format_id,
        'outtmpl': output_template,
        'quiet': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            # --- Get the direct download link from the source ---
            # Re-extract info for the specific format to get the direct URL
            format_info = next((f for f in info['formats'] if f['format_id'] == format_id), None)
            direct_link = format_info.get('url') if format_info else "Not available"

            # --- Check file size and upload to Telegram if possible ---
            if os.path.getsize(filename) > MAX_FILE_SIZE_BYTES:
                final_caption = (
                    f"✅ **Download Complete!**\n\n"
                    f"⚠️ The file is too large for Telegram.\n\n"
                    f"🔗 **Direct Link:** [Click here to download]({direct_link})"
                )
                await query.edit_message_caption(caption=final_caption, parse_mode='Markdown')
            else:
                await query.edit_message_caption(caption="Uploading to Telegram... 🚀")
                with open(filename, 'rb') as video_file:
                    await context.bot.send_video(
                        chat_id=query.message.chat_id, 
                        video=video_file,
                        caption="✅ Here is your video!",
                        supports_streaming=True
                    )
                
                final_caption = (
                    f"✅ **Upload Complete!**\n\n"
                    f"🔗 **Direct Link:** [Click here to download]({direct_link})"
                )
                # We can't edit the caption of the original photo anymore since we sent a new message.
                # So we delete the original thumbnail message.
                await query.message.delete()
                # And send the final status as a new message.
                await context.bot.send_message(chat_id=query.message.chat_id, text=final_caption, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Error during download/upload: {e}")
        await query.edit_message_caption(caption=f"❌ An error occurred during download: {e}")
    finally:
        # --- Clean up the downloaded file from the server ---
        if 'filename' in locals() and os.path.exists(filename):
            os.remove(filename)

def main():
    """Start the bot."""
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, url_handler))
    application.add_handler(CallbackQueryHandler(button_handler))

    application.run_polling()

if __name__ == '__main__':
    main()
