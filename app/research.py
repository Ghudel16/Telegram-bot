from .parser import parse_request

class ResearchEngine:
    def __init__(self, settings, gmgn, router):
        self.settings, self.gmgn, self.router = settings, gmgn, router

    async def research(self, text: str) -> str:
        req = parse_request(text)
        plan = await self.router.plan(text)
        if not self.settings.gmgn_base_url:
            return ('🟡 Research engine siap, tetapi GMGN_BASE_URL belum di-set.\n\n'
                    f'Window: {req.window_hours}h\n'
                    f'ATH MC minimum: ${req.ath_mc_usd:,.0f}\n'
                    f'Minimum coins: {req.min_coins}\n'
                    f'Wallet target: {req.wallet_limit}\n\n'
                    'Set endpoint GMGN yang kamu gunakan di Railway. Setelah itu adapter GMGN diaktifkan.')
        return ('Research plan diterima.\n\n' + plan +
                '\n\nGMGN adapter aktif; endpoint-specific research tools akan dipasang setelah kontrak API/skill diverifikasi.')
