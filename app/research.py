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
        self.last_links = {"wallets": [], "tokens": []}

    @staticmethod
    def _gmgn_url(chain, kind, address):
        if not address:
            return None
        chain_slug = {"sol": "sol", "eth": "eth", "base": "base", "bsc": "bsc", "tron": "tron"}.get(
            str(chain).lower(), str(chain).lower()
        )
        return f"https://gmgn.ai/{chain_slug}/{kind}/{address}"

    @staticmethod
    def _link_label(address, name=None, symbol=None):
        if name or symbol:
            return f"{name or symbol}" + (f" ({symbol})" if name and symbol and name != symbol else "")
        return ResearchEngine._short_wallet(address)

    def _set_links(self, chain, wallets=None, tokens=None):
        result = {"wallets": [], "tokens": []}
        seen_wallets, seen_tokens = set(), set()
        for item in wallets or []:
            address = item if isinstance(item, str) else (item.get("address") if isinstance(item, dict) else None)
            label = None if isinstance(item, str) else (item.get("label") if isinstance(item, dict) else None)
            if address and address not in seen_wallets:
                seen_wallets.add(address)
                result["wallets"].append({
                    "address": address,
                    "label": label or self._short_wallet(address),
                    "url": self._gmgn_url(chain, "address", address),
                })
        for item in tokens or []:
            address = item if isinstance(item, str) else (item.get("address") if isinstance(item, dict) else None)
            label = None if isinstance(item, str) else (item.get("label") if isinstance(item, dict) else None)
            if address and address not in seen_tokens:
                seen_tokens.add(address)
                result["tokens"].append({
                    "address": address,
                    "label": label or self._link_label(address),
                    "url": self._gmgn_url(chain, "token", address),
                })
        self.last_links = {"wallets": result["wallets"][:20], "tokens": result["tokens"][:20]}

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
                        "address": wallet,
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

    async def deep_research(self, text: str) -> str:
        import asyncio
        from collections import defaultdict

        req = parse_request(text or "")
        low = (text or "").lower()
        window_hours = 24
        mc_min = 3_000_000
        wallet_min = 20
        chain = "sol"

        if any(k in low for k in ("48h", "2 hari")):
            window_hours = 48
        elif any(k in low for k in ("7 hari", "7d")):
            window_hours = 168
        if req.ath_mc_usd != 3_000_000:
            mc_min = req.ath_mc_usd
        if req.wallet_limit != 30:
            wallet_min = max(20, min(req.wallet_limit, 50))

        market = await self.gmgn.rank(
            chain=chain,
            interval="24h",
            limit=10,
            order_by="volume",
            min_market_cap=mc_min,
            max_created=str(window_hours) + "h",
        )
        candidates = self._rows(market)[:10]
        if not candidates:
            return "🤖 AI GMGN RESEARCH\n━━━━━━━━━━━━━━━━━━━━\n❌ Tidak ditemukan kandidat coin dengan MC minimum yang diminta."

        category_wallets = {
            "early_buyers": {},
            "early_exit": {},
            "top_traders": {},
            "whales": {},
        }
        source_tokens = {}
        errors = []
        request_gap = 1.25

        def add_wallet(category, row, source, reason=None):
            if not isinstance(row, dict) or not row.get("address"):
                return
            wallet = row["address"]
            category_wallets[category].setdefault(wallet, {
                "address": wallet, "sources": [], "reasons": []
            })
            item = category_wallets[category][wallet]
            if source not in item["sources"]:
                item["sources"].append(source)
            if reason and reason not in item["reasons"]:
                item["reasons"].append(reason)

        for coin in candidates:
            address = coin.get("address")
            if not address:
                continue
            symbol = coin.get("symbol") or coin.get("name") or "UNKNOWN"
            source_tokens[address] = {
                "symbol": symbol,
                "name": coin.get("name"),
                "market_cap": coin.get("market_cap"),
                "ath_market_cap": coin.get("history_highest_market_cap"),
            }
            try:
                raw = await self.gmgn.token_traders_filtered(
                    chain, address, 100, None, "amount_percentage", "desc"
                )
                rows = self._rows(raw)
                regular = [
                    r for r in rows
                    if isinstance(r, dict) and r.get("address")
                    and str(r.get("addr_type", "0")) == "0"
                ]

                early = [r for r in regular if r.get("start_holding_at")]
                early.sort(key=lambda r: self._num(r.get("start_holding_at")))
                for r in early[:wallet_min]:
                    add_wallet("early_buyers", r, symbol, "earliest start_holding_at")

                exits = [
                    r for r in regular
                    if r.get("start_holding_at")
                    and r.get("end_holding_at") not in (None, "", 0, "0")
                    and self._num(r.get("realized_profit")) > 0
                ]
                exits.sort(key=lambda r: self._num(r.get("realized_profit")), reverse=True)
                for r in exits[:wallet_min]:
                    add_wallet("early_exit", r, symbol, "early entry + completed profitable exit")

                for r in regular[:wallet_min]:
                    add_wallet("top_traders", r, symbol, "top trader by amount_percentage")

                await asyncio.sleep(request_gap)
                raw_h = await self.gmgn.token_holders_filtered(
                    chain, address, wallet_min, None, "amount_percentage", "desc"
                )
                holders = [
                    r for r in self._rows(raw_h)
                    if isinstance(r, dict) and r.get("address")
                    and str(r.get("addr_type", "0")) == "0"
                ]
                for r in holders[:wallet_min]:
                    add_wallet("whales", r, symbol, "largest current holder share")

            except Exception as exc:
                errors.append(symbol + ": " + str(exc)[:160])
            await asyncio.sleep(request_gap)

        union = {}
        for category, items in category_wallets.items():
            for wallet, item in items.items():
                union.setdefault(wallet, {"address": wallet, "categories": [], "sources": []})
                union[wallet]["categories"].append(category)
                union[wallet]["sources"].extend(item["sources"])

        selected = sorted(
            union.values(),
            key=lambda x: (-len(set(x["categories"])), -len(x["sources"]))
        )[:60]

        token_wallets = defaultdict(dict)
        activity_errors = 0
        for item in selected:
            wallet = item["address"]
            try:
                raw_a = await self.gmgn.wallet_activity(chain, wallet, 50)
                acts = self._rows(raw_a, keys=("activities", "list"))
                latest = {}
                for act in acts:
                    if not isinstance(act, dict):
                        continue
                    event = str(act.get("event_type") or act.get("type") or "").lower()
                    if event not in ("buy", "sell"):
                        continue
                    tok = act.get("token") or {}
                    token = tok.get("address") or tok.get("token_address")
                    if not token:
                        continue
                    ts = self._num(act.get("timestamp"))
                    if token not in latest or ts >= latest[token]["timestamp"]:
                        latest[token] = {
                            "timestamp": ts,
                            "event": event,
                            "symbol": tok.get("symbol") or tok.get("name") or "UNKNOWN",
                            "address": token,
                        }
                for token, ev in latest.items():
                    if ev["event"] == "buy":
                        token_wallets[token][wallet] = {
                            "status": "BUY/HOLD",
                            "symbol": ev["symbol"],
                            "categories": union[wallet]["categories"],
                            "source_wallet": wallet,
                        }
            except Exception:
                activity_errors += 1
            await asyncio.sleep(1.0)

        overlaps = []
        candidate_tokens = sorted(
            token_wallets.items(), key=lambda kv: len(kv[1]), reverse=True
        )
        source_addresses = set(source_tokens)
        for token, wallets in candidate_tokens:
            if token in source_addresses or len(wallets) < 3:
                continue
            try:
                info = await self.gmgn.token_info(chain, token)
            except Exception:
                info = {}
            info = info if isinstance(info, dict) else {}
            price = info.get("price") if isinstance(info.get("price"), dict) else {}
            supply = self._num(info.get("circulating_supply") or info.get("total_supply"))
            px = self._num(price.get("price"))
            current_mc = self._num(info.get("market_cap")) or (px * supply if px and supply else 0)
            overlaps.append({
                "address": token,
                "symbol": next(iter(wallets.values())).get("symbol") or info.get("symbol") or "UNKNOWN",
                "name": info.get("name"),
                "market_cap": current_mc,
                "wallet_count": len(wallets),
                "wallets": list(wallets.values())[:20],
            })
            await asyncio.sleep(0.75)
            if len(overlaps) >= 15:
                break

        overlaps.sort(key=lambda x: x["wallet_count"], reverse=True)
        wallet_links = []
        token_links = []
        for item in overlaps:
            token_links.append({"address": item["address"], "label": item["symbol"]})
            for w in item["wallets"]:
                wallet_links.append({"address": w["source_wallet"]})
        self._set_links(chain, wallet_links, token_links)

        payload = {
            "mode": "deep_wallet_convergence",
            "chain": chain,
            "window_label": str(window_hours) + " jam",
            "candidate_rule": "MC >= $" + str(mc_min) + " and token age <= " + str(window_hours) + "h",
            "wallet_min_per_category": wallet_min,
            "category_counts": {name: len(items) for name, items in category_wallets.items()},
            "candidate_count": len(candidates),
            "final_overlaps": overlaps,
            "activity_errors": activity_errors,
            "rate_limit_or_api_errors": errors[:20],
            "status_basis": "wallet_activity: latest observed event is BUY; this is a current-activity proxy, not an exact holdings snapshot.",
            "important_limit": "Exact current holdings require GMGN portfolio holdings, documented as critical-auth (API key + private key).",
        }
        return (await self.router.synthesize(text, payload))[:3900]

    async def research(self, text: str) -> str:
        self.last_links = {"wallets": [], "tokens": []}
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
            (
                "awal" in low
                or "early" in low
                or "early-buyer" in low
                or "early buyer" in low
                or "marketcap kecil" in low
                or "market cap kecil" in low
                or "low mc" in low
                or "low market cap" in low
            )
            and ("wallet" in low or "walet" in low)
            and ("hold" in low or "beli" in low or "buy" in low or "currently" in low)
            and (
                "3 wallet" in low
                or "3 wallets" in low
                or "3+ " in low
                or "3+" in low
                or "minimal 3" in low
                or ">=3" in low
                or "same early-buyer" in low
                or "same early buyer" in low
                or "overlap" in low
            )
        )
        if early_wallet_request:
            payload = await self._early_wallet_overlap(text, chain, req)
            wallet_links = []
            token_links = []
            for item in payload.get("overlaps", []):
                if item.get("address"):
                    token_links.append({"address": item["address"], "label": item.get("symbol") or item.get("token") or "Token"})
                for wallet in item.get("wallets", []):
                    if wallet.get("address"):
                        wallet_links.append({"address": wallet["address"]})
            self._set_links(chain, wallet_links, token_links)
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
                self._set_links(chain, [{"address": address}], [])
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
            wallet_links = []
            for row in self._rows(holders_data) + self._rows(traders_data):
                if isinstance(row, dict) and row.get("address"):
                    wallet_links.append({"address": row["address"]})
            self._set_links(
                chain,
                wallet_links,
                [{"address": address, "label": summary.get("symbol") or summary.get("name") or "Token"}],
            )
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
        self._set_links(
            chain,
            [],
            [
                {"address": row.get("address"), "label": self._link_label(row.get("address"), row.get("name"), row.get("symbol"))}
                for row in self._rows(data)
                if isinstance(row, dict) and row.get("address")
            ],
        )
        return (await self.router.synthesize(text, payload))[:3900]
