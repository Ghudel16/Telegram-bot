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

    @staticmethod
    def _rows(obj, keys=("list", "activities", "rank")):
        if isinstance(obj, list):
            return obj
        if isinstance(obj, dict):
            for key in keys:
                value = obj.get(key)
                if isinstance(value, list):
                    return value
            nested = obj.get("data")
            if isinstance(nested, dict):
                for key in keys:
                    value = nested.get(key)
                    if isinstance(value, list):
                        return value
        return []

    @staticmethod
    def _num(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _short_wallet(address):
        if not address:
            return "N/A"
        return f"{address[:6]}…{address[-4:]}"

    @staticmethod
    def _early_wallets(rows, limit=20):
        valid = [
            r for r in rows
            if isinstance(r, dict)
            and r.get("address")
            and r.get("start_holding_at")
            and str(r.get("addr_type", "0")) == "0"
        ]
        valid.sort(key=lambda r: ResearchEngine._num(r.get("start_holding_at")))
        return valid[:limit]

    async def _early_wallet_overlap(self, text, chain, req):
        # The token-trader endpoint exposes first-acquisition timing and current
        # position metrics. We use the earliest 20 returned trader records per
        # candidate token, then look for those same wallets in other candidates.
        # This is deliberately limited to 8 candidates to avoid hammering GMGN's
        # weighted trader endpoint.
        if req.window_hours <= 24:
            interval, period_label, max_created = "24h", "24 jam", "24h"
        elif req.window_hours <= 168:
            interval, period_label, max_created = "24h", "7 hari", "7d"
        else:
            interval, period_label, max_created = "24h", "30 hari", "30d"

        market = await self.gmgn.rank(
            chain=chain,
            interval=interval,
            limit=max(20, min(req.min_coins, 20)),
            order_by="history_highest_market_cap",
            min_history_highest_market_cap=req.ath_mc_usd,
            max_created=max_created,
        )
        candidates = self._rows(market)[:8]
        if not candidates:
            return {
                "mode": "early_wallet_overlap",
                "window_label": period_label,
                "error": "GMGN tidak mengembalikan kandidat token."
            }

        token_scans = []
        global_early = {}
        trader_maps = {}

        for coin in candidates:
            address = coin.get("address")
            if not address:
                continue
            try:
                raw = await self.gmgn.top_traders(chain, address, 100)
            except Exception as exc:
                token_scans.append({
                    "token": coin.get("symbol") or coin.get("name") or "Unknown",
                    "address": address,
                    "error": str(exc)[:180],
                })
                continue

            rows = self._rows(raw)
            early = self._early_wallets(rows, 20)
            if len(early) < 20:
                token_scans.append({
                    "token": coin.get("symbol") or coin.get("name") or "Unknown",
                    "address": address,
                    "early_wallets": len(early),
                    "eligible": False,
                })
                continue

            by_wallet = {r["address"]: r for r in rows if r.get("address")}
            trader_maps[address] = by_wallet
            token_scans.append({
                "token": coin.get("symbol") or coin.get("name") or "Unknown",
                "symbol": coin.get("symbol"),
                "address": address,
                "market_cap": coin.get("market_cap"),
                "ath_market_cap": coin.get("history_highest_market_cap"),
                "early_wallets": len(early),
                "eligible": True,
            })
            for row in early:
                wallet = row["address"]
                global_early.setdefault(wallet, set()).add(address)

        overlaps = []
        for target in token_scans:
            target_addr = target.get("address")
            if not target_addr or not target.get("eligible") or target_addr not in trader_maps:
                continue

            hits = {}
            for wallet, origin_tokens in global_early.items():
                if target_addr in origin_tokens:
                    continue
                row = trader_maps[target_addr].get(wallet)
                if not row:
                    continue

                buy = self._num(row.get("buy_volume_cur"))
                sell = self._num(row.get("sell_volume_cur"))
                net_amount = self._num(row.get("netflow_amount"))
                hold = (
                    (row.get("end_holding_at") in (None, "", 0, "0"))
                    and (net_amount > 0 or self._num(row.get("amount_cur")) > 0)
                )
                buying = buy > 0 and buy >= sell
                if hold or buying:
                    status = "BUYING" if buying else "HOLD"
                    hits[wallet] = {
                        "wallet": self._short_wallet(wallet),
                        "status": status,
                        "hold_pct": row.get("amount_percentage"),
                        "buy_volume": row.get("buy_volume_cur"),
                        "sell_volume": row.get("sell_volume_cur"),
                        "unrealized_profit": row.get("unrealized_profit"),
                        "tags": row.get("tags") or row.get("maker_token_tags") or [],
                        "origin_count": len(global_early.get(wallet, set())),
                    }

            if len(hits) >= 3:
                overlaps.append({
                    "token": target.get("token"),
                    "symbol": target.get("symbol"),
                    "address": target_addr,
                    "market_cap": target.get("market_cap"),
                    "ath_market_cap": target.get("ath_market_cap"),
                    "shared_wallet_count": len(hits),
                    "wallets": list(hits.values())[:20],
                })

        overlaps.sort(key=lambda x: x["shared_wallet_count"], reverse=True)
        return {
            "mode": "early_wallet_overlap",
            "window_label": period_label,
            "chain": chain,
            "rule": "Earliest 20 wallets per candidate token by start_holding_at; show another token only when >=3 of those wallets are currently holding or have current buy flow in it.",
            "current_status_basis": "GMGN trader fields: end_holding_at, amount_cur/netflow_amount, buy_volume_cur and sell_volume_cur.",
            "candidate_count": len(candidates),
            "eligible_tokens": sum(1 for x in token_scans if x.get("eligible")),
            "token_scans": token_scans,
            "overlaps": overlaps[:20],
        }

    async def research(self, text: str) -> str:
        req = parse_request(text)
        address = extract_address(text)
        chain = detect_chain(text)

        if not self.settings.gmgn_api_key:
            return "❌ GMGN_API_KEY belum dikonfigurasi di Railway."

        # Some research requests need deterministic multi-token wallet analysis.
        # Detect these before the generic AI planner so the planner cannot reduce
        # the request to a simple market summary.
        low = text.lower()
        early_wallet_request = (
            ("awal" in low or "early" in low or "marketcap kecil" in low or "market cap kecil" in low)
            and ("wallet" in low or "walet" in low)
            and ("hold" in low or "beli" in low or "buy" in low)
            and ("3 wallet" in low or "3 wallets" in low or "minimal 3" in low or ">=3" in low)
        )
        if early_wallet_request:
            payload = await self._early_wallet_overlap(text, chain, req)
            return (await self.router.synthesize(text, payload))[:3900]

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
            holders = await self.gmgn.top_holders(chain, address, max(req.wallet_limit, 10))
            traders = await self.gmgn.top_traders(chain, address, max(req.wallet_limit, 10))

            token_data = compact(info)
            security_data = compact(security)
            pool_data = compact(pool)
            holders_data = compact(holders)
            traders_data = compact(traders)

            def rows(obj):
                if isinstance(obj, dict):
                    for key in ("holders", "list", "data", "top_holders", "rank"):
                        value = obj.get(key)
                        if isinstance(value, list):
                            return value
                return obj if isinstance(obj, list) else []

            holder_rows = rows(holders_data)[:10]

            def first_value(*sources):
                for source, keys in sources:
                    if isinstance(source, dict):
                        for key in keys:
                            value = source.get(key)
                            if value not in (None, ""):
                                return value
                return None

            top10_rate = first_value(
                (token_data, ("top_10_holder_rate", "top10_holder_rate")),
                (security_data, ("top_10_holder_rate", "top10_holder_rate")),
                (holders_data, ("top_10_holder_rate", "top10_holder_rate")),
            )

            summary = {
                "name": first_value((token_data, ("name",))),
                "symbol": first_value((token_data, ("symbol",))),
                "price": first_value((token_data, ("price",))),
                "market_cap": first_value((token_data, ("market_cap", "market_cap_usd", "mc"))),
                "ath_price": first_value((token_data, ("ath_price",))),
                "ath_market_cap": first_value((token_data, ("ath_market_cap", "history_highest_market_cap", "history_highest_mc"))),
                "ath_timestamp": first_value((token_data, ("ath_ts", "ath_timestamp", "history_highest_market_cap_timestamp"))),
                "liquidity": first_value((token_data, ("liquidity", "liquidity_usd"))),
                "volume_24h": first_value((token_data, ("volume_24h", "volume", "volume_usd"))),
                "holder_count": first_value((token_data, ("holder_count",))),
                "top_10_holder_rate": top10_rate,
                "creator_hold_rate": first_value((token_data, ("creator_hold_rate",)), (security_data, ("creator_hold_rate",))),
                "dev_team_hold_rate": first_value((token_data, ("dev_team_hold_rate",)), (security_data, ("dev_team_hold_rate",))),
                "wallet_tags_stat": token_data.get("wallet_tags_stat") if isinstance(token_data, dict) else None,
            }

            payload = {
                "mode": "token_research",
                "chain": chain,
                "address": address,
                "summary": summary,
                "token": token_data,
                "security": security_data,
                "pool": pool_data,
                "top_10_holders": holder_rows,
                "top_10_holder_rate": top10_rate,
                "top_holders": holders_data,
                "top_traders": traders_data,
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
