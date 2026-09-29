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

def compact(obj, max_items=8):
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

        # Discovery mode: current GMGN market ranking. A 7d/30d request is kept
        # as the requested research window, but we don't pretend the current rank
        # endpoint is historical ATH data.
        interval = "24h"
        if "1h" in low: interval = "1h"
        elif "6h" in low: interval = "6h"

        data = await self.gmgn.rank(chain, interval, max(req.min_coins, 30))
        payload = {
            "mode": "market_discovery",
            "requested_window_hours": req.window_hours,
            "ath_mc_min_usd": req.ath_mc_usd,
            "chain": chain,
            "interval_used": interval,
            "market_rank": compact(data, 12),
        }
        return (await self.router.synthesize(text, payload))[:3900]
