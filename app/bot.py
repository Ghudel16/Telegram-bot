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
    router = AIRouter(settings)
    engine = ResearchEngine(settings, gmgn, router)

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🤖 GMGN AI Research Bot aktif.\n\n"
            "• Kirim CA token untuk deep research\n"
            "• Kirim wallet Solana untuk wallet analysis\n"
            "• Cari market Solana 24h\n\n"
            "Bot hanya membaca data dan tidak melakukan trading."
        )

    async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message is None:
            return
        if settings.allowed_ids and update.effective_user and update.effective_user.id not in settings.allowed_ids:
            await update.message.reply_text("Akses tidak diizinkan.")
            return
        await update.message.chat.send_action(ChatAction.TYPING)
        try:
            result = await engine.research(update.message.text or "")
        except Exception as exc:
            result = f"❌ Research error: {str(exc)[:1000]}"
        await update.message.reply_text(result[:4000])

    app = Application.builder().token(settings.telegram_bot_token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

    domain = settings.railway_public_domain
    if not domain:
        raise RuntimeError("RAILWAY_PUBLIC_DOMAIN belum dikonfigurasi.")
    webhook_url = f"https://{domain}/{settings.webhook_path}"

    try:
        await app.initialize()
        await app.start()
        await app.updater.start_webhook(
            listen="0.0.0.0",
            port=settings.port,
            url_path=settings.webhook_path,
            webhook_url=webhook_url,
        )
        import asyncio
        await asyncio.Event().wait()
    finally:
        await gmgn.close()
        await router.close()

if __name__ == "__main__":
    import asyncio
    asyncio.run(run())
