import re
from .parser import parse_request

SOL_RE = re.compile(r"(?<![A-Za-z0-9])[1-9A-HJ-NP-Za-km-z]{32,44}(?![A-Za-z0-9])")
EVM_RE = re.compile(r"0x[a-fA-F0-9]{40}")

def detect_chain(text: str) -> str:
    if EVM_RE.search(text):
        return "eth"
    return "sol"

def extract_address(text: str):
    m = EVM_RE.search(text) or SOL_RE.search(text)
    return m.group(0) if m else None

def compact(obj, max_items=20):
    if isinstance(obj, dict):
        return {k: compact(v, max_items) for k, v in list(obj.items())[:max_items]}
    if isinstance(obj, list):
        return [compact(v, max_items) for v in obj[:max_items]]
    return obj

class ResearchEngine:
    def __init__(self, settings, gmgn, router):
        self.settings, self.gmgn, self.router = settings, gmgn, router

    async def research(self, text: str) -> str:
        req = parse_request(text)
        address = extract_address(text)
        chain = detect_chain(text)
        low = text.lower()

        if not self.settings.gmgn_api_key:
            return "❌ GMGN_API_KEY belum dikonfigurasi di Railway."

        if address:
            info = await self.gmgn.token_info(chain, address)
            security = await self.gmgn.token_security(chain, address)
            pool = await self.gmgn.token_pool(chain, address)
            holders = await self.gmgn.top_holders(chain, address, req.wallet_limit)
            traders = await self.gmgn.top_traders(chain, address, req.wallet_limit)

            payload = {
                "chain": chain,
                "address": address,
                "token": compact(info),
                "security": compact(security),
                "pool": compact(pool),
                "top_holders": compact(holders),
                "top_traders": compact(traders),
            }
            answer = await self.router.synthesize(text, payload)
            return answer[:3900]

        # GMGN trending itself supports intervals only up to 24h. For longer
        # requests, use the requested period as a token-age universe while the
        # ATH field remains explicitly all-time (history_highest_market_cap).
        if req.window_hours <= 24:
            interval = "24h"
            period_label = "24 jam"
            order_by = "volume"
            max_created = "24h"
        elif req.window_hours <= 168:
            interval = "24h"
            period_label = "7 hari"
            order_by = "history_highest_market_cap"
            max_created = "7d"
        else:
            interval = "24h"
            period_label = "30 hari"
            order_by = "history_highest_market_cap"
            max_created = "30d"

        data = await self.gmgn.rank(
            chain=chain,
            interval=interval,
            limit=max(req.min_coins, 30),
            order_by=order_by,
            min_history_highest_market_cap=req.ath_mc_usd,
            max_created=max_created,
        )

        payload = {
            "mode": "market_discovery",
            "requested_window_hours": req.window_hours,
            "window_label": period_label,
            "ath_mc_min_usd": req.ath_mc_usd,
            "chain": chain,
            "interval_used": interval,
            "universe_rule": f"token creation age <= {max_created}",
            "ath_definition": "history_highest_market_cap = GMGN all-time highest market cap",
            "sort": order_by,
            "market_rank": compact(data, 20),
        }
        return (await self.router.synthesize(text, payload))[:3900]
