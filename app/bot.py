from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from .config import Settings
from .gmgn import GMGNClient
from .router import AIRouter
from .research import ResearchEngine

async def run():
    settings = Settings()
    gmgn = GMGNClient(settings)
    engine = ResearchEngine(settings, gmgn, AIRouter(settings))

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text('🤖 GMGN AI Research Bot siap.\n\nContoh:\n• Cari coin ATH > $3M dalam 7 hari terakhir\n• Research token/CA dan cari 30 wallet penting\n• Bandingkan wallet dari beberapa coin')

    async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message is None:
            return
        if settings.allowed_ids and update.effective_user and update.effective_user.id not in settings.allowed_ids:
            await update.message.reply_text('Akses tidak diizinkan.')
            return
        await update.message.chat.send_action(ChatAction.TYPING)
        try:
            result = await engine.research(update.message.text or '')
        except Exception as exc:
            result = f'❌ Research error: {exc}'
        await update.message.reply_text(result[:4000])

    app = Application.builder().token(settings.telegram_bot_token).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    import asyncio
    try:
        await asyncio.Event().wait()
    finally:
        await gmgn.close()

if __name__ == '__main__':
    import asyncio
    asyncio.run(run())
