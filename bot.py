import os
import logging
import yt_dlp
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# --- (Logging and Token setup remains the same) ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)
TELEGRAM_TOKEN = "YOUR_HTTP_API_TOKEN"
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024

def format_bytes(size):
    if size is None: return "N/A"
    power = 1024
    n = 0
    power_labels = {0: '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
    while size > power and n < len(power_labels) - 1:
        size /= power
        n += 1
    return f"{size:.1f}{power_labels[n]}B"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hi! Send me a video link. I'll show you the available download options."
    )

async def url_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    formats = sorted(
        [f for f in info.get('formats', []) if f.get('vcodec') != 'none' and f.get('acodec') != 'none' and f.get('ext') == 'mp4'],
        key=lambda f: f.get('height', 0) or 0,
        reverse=True
    )
    
    MAX_BUTTONS = 10
    for f in formats[:MAX_BUTTONS]:
        format_id = f.get('format_id')
        resolution = f.get('format_note') or f"{f.get('height')}p"
        filesize = f.get('filesize') or f.get('filesize_approx')
        filesize_str = format_bytes(filesize)
        button_text = f"{f.get('ext')} - {resolution} ({filesize_str})"
        
        # CHANGED: Callback data is now much shorter
        callback_data = f"dl_{format_id}" 
        keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])

    if not keyboard:
        await processing_msg.edit_text("❌ No downloadable MP4 versions found.")
        return

    reply_markup = InlineKeyboardMarkup(keyboard)
    thumbnail_url = info.get('thumbnail')
    
    # Send the reply and get the message object
    if thumbnail_url:
        sent_message = await update.message.reply_photo(
            photo=thumbnail_url,
            caption=f"🎬 **{info.get('title')}**\n\nSelect a version to download:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    else:
        sent_message = await update.message.reply_text(
            f"🎬 **{info.get('title')}**\n\nSelect a version to download:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    # NEW: Save the original URL in chat_data, keyed by the message ID of our reply
    # This links the button press back to the correct URL.
    context.chat_data[sent_message.message_id] = url
    await processing_msg.delete()

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # CHANGED: Retrieve the URL from chat_data using the message ID
    message_id = query.message.message_id
    if message_id not in context.chat_data:
        await query.edit_message_caption(caption="❌ This download link has expired. Please send the URL again.")
        return
    
    url = context.chat_data[message_id]
    format_id = query.data.split('_', 1)[1] # Extracts the format_id from "dl_{format_id}"

    await query.edit_message_caption(caption="Downloading to server... 📥")

    output_template = f'%(id)s_{format_id}.mp4'
    ydl_opts = {
        'format': format_id,
        'outtmpl': output_template,
        'quiet': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            format_info = next((f for f in info['formats'] if f['format_id'] == format_id), None)
            direct_link = format_info.get('url') if format_info else "Not available"

            if os.path.getsize(filename) > MAX_FILE_SIZE_BYTES:
                final_caption = (f"✅ **Download Complete!**\n\n⚠️ File too large for Telegram.\n\n🔗 **Direct Link:** [Click here]({direct_link})")
                await query.edit_message_caption(caption=final_caption, parse_mode='Markdown')
            else:
                await query.edit_message_caption(caption="Uploading to Telegram... 🚀")
                with open(filename, 'rb') as video_file:
                    await context.bot.send_video(chat_id=query.message.chat_id, video=video_file, caption="✅ Here is your video!", supports_streaming=True)
                
                final_caption = (f"✅ **Upload Complete!**\n\n🔗 **Direct Link:** [Click here]({direct_link})")
                await query.message.delete()
                await context.bot.send_message(chat_id=query.message.chat_id, text=final_caption, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Error during download/upload: {e}")
        await query.edit_message_caption(caption=f"❌ An error occurred during download.")
    finally:
        if 'filename' in locals() and os.path.exists(filename):
            os.remove(filename)
        # NEW: Clean up the stored URL from memory
        if message_id in context.chat_data:
            del context.chat_data[message_id]

def main():
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, url_handler))
    # CHANGED: The callback handler now looks for data starting with "dl_"
    application.add_handler(CallbackQueryHandler(button_handler, pattern='^dl_'))
    application.run_polling()

if __name__ == '__main__':
    main()
