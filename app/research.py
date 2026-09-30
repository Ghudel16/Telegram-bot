import re
from .parser import parse_request

SOL_RE = re.compile(r"(?<![A-Za-z0-9])[1-9A-HJ-NP-Za-km-z]{32,44}(?![A-Za-z0-9])")
EVM_RE = re.compile(r"0x[a-fA-F0-9]{40}")


def detect_chain(text: str) -> str:
    return "eth" if EVM_RE.search(text) else "sol"


def extract_address(text: str):
    m = EVM_RE.search(text) or SOL_RE.search(text)
    return m.group(0) if m else None


def compact(obj, max_items=30):
    if isinstance(obj, dict):
        return {k: compact(v, max_items) for k, v in list(obj.items())[:max_items]}
    if isinstance(obj, list):
        return [compact(v, max_items) for v in obj[:max_items]]
    return obj


def compact_rank(data):
    raw = data.get("data", data) if isinstance(data, dict) else {}
    if not isinstance(raw, dict):
        return data
    rows = raw.get("rank") or []
    selected = []
    keep = [
        "address", "name", "symbol", "price", "price_change_percent",
        "market_cap", "market_cap_usd", "history_highest_market_cap",
        "liquidity", "liquidity_usd", "volume", "volume_24h", "volume_usd",
        "holder_count", "smart_degen_count", "renowned_count",
        "buys", "sells", "swaps", "creation_timestamp",
        "launchpad_platform", "exchange", "is_honeypot", "is_mintable",
    ]
    for row in rows[:30]:
        if isinstance(row, dict):
            selected.append({k: row.get(k) for k in keep if k in row})
    return {"rank": selected}


class ResearchEngine:
    def __init__(self, settings, gmgn, router):
        self.settings, self.gmgn, self.router = settings, gmgn, router

    async def research(self, text: str) -> str:
        req = parse_request(text)
        address = extract_address(text)
        chain = detect_chain(text)

        if not self.settings.gmgn_api_key:
            return "❌ GMGN_API_KEY belum dikonfigurasi di Railway."

        # First try to classify the free-form question with the AI router.
        # If all AI providers fail, deterministic routing still works.
        intent = None
        if len(text.strip()) > 2:
            try:
                plan_raw = await self.router.plan(text)
                import json
                plan = json.loads(plan_raw)
                intent = plan.get("intent")
            except Exception:
                pass

        # Explicit wallet wording takes precedence over an ambiguous Solana address.
        wallet_words = ("wallet", "walet", "address wallet", "portfolio", "aktivitas wallet")
        if address and any(w in text.lower() for w in wallet_words):
            try:
                stats = await self.gmgn.wallet_stats(chain, address)
                activity = await self.gmgn.wallet_activity(chain, address, req.wallet_limit)
                payload = {
                    "mode": "wallet_research",
                    "chain": chain,
                    "address": address,
                    "wallet_stats": compact(stats),
                    "wallet_activity": compact(activity),
                }
                return (await self.router.synthesize(text, payload))[:3900]
            except Exception:
                pass

        # Token CA research. A Solana address is treated as a token by default,
        # matching the original bot behaviour.
        if address and intent != "wallet":
            info = await self.gmgn.token_info(chain, address)
            security = await self.gmgn.token_security(chain, address)
            pool = await self.gmgn.token_pool(chain, address)
            holders = await self.gmgn.top_holders(chain, address, req.wallet_limit)
            traders = await self.gmgn.top_traders(chain, address, req.wallet_limit)
            payload = {
                "mode": "token_research",
                "chain": chain,
                "address": address,
                "token": compact(info),
                "security": compact(security),
                "pool": compact(pool),
                "top_holders": compact(holders),
                "top_traders": compact(traders),
            }
            return (await self.router.synthesize(text, payload))[:3900]

        # Conceptual questions can be answered by AI without wasting a GMGN
        # market request. The AI is told that no live GMGN data was supplied.
        if intent == "explain" and not any(k in text.lower() for k in ("coin", "token", "trader", "holder", "wallet", "market", "volume", "liquidity", "mc", "ath")):
            payload = {
                "mode": "explain",
                "gmgn_data_available": False,
                "note": "No live GMGN market/token payload was needed for this conceptual question.",
            }
            return (await self.router.synthesize(text, payload))[:3900]

        # GMGN trending supports intervals up to 24h. Longer requests use token
        # age as the discovery universe and retain the all-time ATH definition.
        if req.window_hours <= 24:
            interval, period_label, order_by, max_created = "24h", "24 jam", "volume", "24h"
        elif req.window_hours <= 168:
            interval, period_label, order_by, max_created = "24h", "7 hari", "history_highest_market_cap", "7d"
        else:
            interval, period_label, order_by, max_created = "24h", "30 hari", "history_highest_market_cap", "30d"

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
            "user_question": text,
            "requested_window_hours": req.window_hours,
            "window_label": period_label,
            "ath_mc_min_usd": req.ath_mc_usd,
            "chain": chain,
            "interval_used": interval,
            "universe_rule": f"token creation age <= {max_created}",
            "ath_definition": "history_highest_market_cap = GMGN all-time highest market cap",
            "sort": order_by,
            "market_rank": compact_rank(data),
        }
        return (await self.router.synthesize(text, payload))[:3900]
