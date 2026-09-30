from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
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

    def gmgn_keyboard(links):
        rows = []
        wallets = links.get("wallets") or []
        tokens = links.get("tokens") or []

        if wallets:
            rows.append([InlineKeyboardButton("👛 WALLETS — GMGN", url=wallets[0]["url"])])
            for i in range(0, len(wallets), 2):
                row = []
                for item in wallets[i:i + 2]:
                    row.append(InlineKeyboardButton(item["label"][:32], url=item["url"]))
                rows.append(row)

        if tokens:
            rows.append([InlineKeyboardButton("🪙 COINS — GMGN", url=tokens[0]["url"])])
            for i in range(0, len(tokens), 2):
                row = []
                for item in tokens[i:i + 2]:
                    row.append(InlineKeyboardButton(item["label"][:32], url=item["url"]))
                rows.append(row)

        return InlineKeyboardMarkup(rows) if rows else None

    async def deep_research_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message is None:
            return
        if settings.allowed_ids and update.effective_user and update.effective_user.id not in settings.allowed_ids:
            await update.message.reply_text("Akses tidak diizinkan.")
            return
        await update.message.chat.send_action(ChatAction.TYPING)
        extra = " ".join(context.args).strip()
        # Telegram command names cannot contain spaces, so /riset_mendalam is the
        # canonical command. /riset mendalam ... is accepted as a convenience alias.
        user_request = extra or (
            "Lakukan riset mendalam default: cari coin Solana yang mencapai MC "
            "minimal $3M dalam 24 jam, ambil minimal 20 wallet per kategori "
            "(early buyer, early holder yang sudah exit profit, top trader, whale), "
            "lalu cari token lain yang sedang BUY/HOLD oleh minimal 3 wallet yang sama. "
            "Tampilkan hanya token hasil overlap akhir."
        )
        try:
            result = await engine.deep_research(user_request)
        except Exception as exc:
            result = f"❌ Deep research error: {str(exc)[:1000]}"
        markup = gmgn_keyboard(getattr(engine, "last_links", {}))
        await update.message.reply_text(result[:4000], reply_markup=markup)

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
        markup = gmgn_keyboard(getattr(engine, "last_links", {}))
        await update.message.reply_text(result[:4000], reply_markup=markup)

    app = Application.builder().token(settings.telegram_bot_token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("riset_mendalam", deep_research_command))
    app.add_handler(CommandHandler("risetmendalam", deep_research_command))
    app.add_handler(CommandHandler("riset", deep_research_command))
    await app.bot.set_my_commands([
        ("start", "Start bot"),
        ("riset_mendalam", "Deep GMGN wallet convergence research"),
    ])
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
