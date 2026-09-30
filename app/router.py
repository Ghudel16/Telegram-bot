import httpx
import json
from typing import Any


class AIRouter:
    """Multi-provider AI router.

    Every provider is treated as an OpenAI-compatible gateway except Gemini.
    Providers are attempted in configured order. A timeout, 4xx/5xx, malformed
    response, or model error automatically advances to the next provider.
    """

    def __init__(self, settings):
        self.settings = settings
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10, read=55, write=20, pool=10)
        )
        self.last_provider = None
        self.last_errors: list[str] = []
        self._rr_cursor = 0

    def _providers(self):
        mapping = {
            "9router": (self.settings.ninerouter_key or "", self.settings.ninerouter_url, self.settings.ninerouter_model),
            "agentrouter": (self.settings.agentrouter_api_key, self.settings.agentrouter_base_url, self.settings.agentrouter_model),
            "gemini": (self.settings.gemini_api_key, None, "gemini-2.5-flash"),
            "seekai": (self.settings.seekai_api_key, self.settings.seekai_base_url, self.settings.seekai_model),
            "kapibala": (self.settings.kapibala_api_key, self.settings.kapibala_base_url, self.settings.kapibala_model),
            "tokenharbor": (self.settings.tokenharbor_api_key, self.settings.tokenharbor_base_url, self.settings.tokenharbor_model),
            "xkiro": (self.settings.xkiro_api_key, self.settings.xkiro_base_url, self.settings.xkiro_model),
            "infercom": (self.settings.infercom_api_key, self.settings.infercom_base_url, self.settings.infercom_model),
            "morphllm": (self.settings.morphllm_api_key, self.settings.morphllm_base_url, self.settings.morphllm_model),
            "iamhc": (self.settings.iamhc_api_key, self.settings.iamhc_base_url, self.settings.iamhc_model),
            "conduit": (self.settings.conduit_api_key, self.settings.conduit_base_url, self.settings.conduit_model),
            "conduit2": (self.settings.conduit_api_key_2, self.settings.conduit_base_url, self.settings.conduit_model),
        }
        order = [x.strip().lower() for x in self.settings.ai_router_order.split(",") if x.strip()]
        for name in order:
            item = mapping.get(name)
            if item and item[0]:
                yield name, *item

    @staticmethod
    def _unwrap(value: Any) -> Any:
        if isinstance(value, dict) and "data" in value:
            return value["data"]
        return value

    @staticmethod
    def _first(obj: dict, *keys):
        for key in keys:
            value = obj.get(key)
            if value is not None and value != "":
                return value
        return None

    @staticmethod
    def _num(value: Any, money: bool = False) -> str:
        if value is None:
            return "N/A"
        try:
            n = float(value)
            if money:
                if abs(n) >= 1_000_000_000:
                    return "$" + f"{n/1_000_000_000:.2f}B"
                if abs(n) >= 1_000_000:
                    return "$" + f"{n/1_000_000:.2f}M"
                if abs(n) >= 1_000:
                    return "$" + f"{n/1_000:.2f}K"
                return "$" + f"{n:.4g}"
            if abs(n) >= 1_000_000_000:
                return f"{n/1_000_000_000:.2f}B"
            if abs(n) >= 1_000_000:
                return f"{n/1_000_000:.2f}M"
            if abs(n) >= 1_000:
                return f"{n/1_000:.2f}K"
            return f"{n:.6g}"
        except (TypeError, ValueError):
            return str(value)

    @staticmethod
    def _change(value: Any) -> str:
        if value is None:
            return "N/A"
        try:
            return f"{float(value):+.2f}%"
        except (TypeError, ValueError):
            return str(value)

    async def _call(self, name: str, key: str, base_url: str | None, model: str, messages: list[dict]) -> str:
        if name == "gemini":
            prompt = "\n\n".join(
                f"{m['role'].upper()}:\n{m['content']}" for m in messages
            )
            r = await self.client.post(
                "https://generativelanguage.googleapis.com/v1beta/models/" + model + ":generateContent",
                params={"key": key},
                json={"contents": [{"parts": [{"text": prompt}]}]},
            )
            r.raise_for_status()
            data = r.json()
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()

        base = (base_url or "").rstrip("/")
        if not base:
            raise RuntimeError("provider base URL missing")

        # 9Router exposes an OpenAI-compatible gateway.
        # With model=auto, discover a configured model dynamically.
        if name == "9router" and model in ("", "auto"):
            headers = {"Content-Type": "application/json"}
            if key:
                headers["Authorization"] = f"Bearer {key}"
            mr = await self.client.get(base + "/v1/models", headers=headers)
            mr.raise_for_status()
            models = (mr.json().get("data") or [])
            if not models:
                raise RuntimeError("9router has no configured models/providers")
            model = models[0].get("id")
            if not model:
                raise RuntimeError("9router returned no usable model")

        url = base + ("/v1/chat/completions" if name == "9router" else "/chat/completions")
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        r = await self.client.post(
            url,
            headers=headers,
            json={
                "model": model,
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": 1800,
                "stream": False,
            },
        )
        r.raise_for_status()
        data = r.json()
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("provider returned no choices")
        content = (choices[0].get("message") or {}).get("content")
        if isinstance(content, list):
            content = "".join(x.get("text", "") for x in content if isinstance(x, dict))
        if not content:
            raise RuntimeError("provider returned empty content")
        return str(content).strip()

    async def ask(self, messages: list[dict]) -> str:
        self.last_errors = []
        providers = list(self._providers())
        if not providers:
            raise RuntimeError("Tidak ada AI provider yang memiliki konfigurasi key.")

        # Round-robin across configured providers. A failed provider is skipped,
        # while a successful provider becomes the starting point for the next call.
        start = self._rr_cursor % len(providers)
        ordered = providers[start:] + providers[:start]
        for offset, (name, key, base_url, model) in enumerate(ordered):
            try:
                answer = await self._call(name, key, base_url, model, messages)
                if answer:
                    self.last_provider = name
                    self._rr_cursor = (start + offset + 1) % len(providers)
                    return answer
            except Exception as exc:
                self.last_errors.append(f"{name}: {str(exc)[:180]}")
        self.last_provider = None
        raise RuntimeError("Semua AI provider gagal: " + " | ".join(self.last_errors[:6]))

    async def plan(self, user_text: str) -> str:
        messages = [
            {"role": "system", "content": (
                "You are an intent planner for a GMGN research agent. "
                "Return ONLY valid JSON: {\"intent\":\"token|wallet|market|explain\",\"depth\":\"quick|deep\"}. "
                "Token means token/CA research, wallet means wallet activity, market means discovery/rankings, "
                "explain means conceptual GMGN questions. Never invent addresses."
            )},
            {"role": "user", "content": user_text},
        ]
        return await self.ask(messages)

    async def synthesize(self, request_text: str, research_payload) -> str:
        prompt = (
            "Anda adalah AI crypto/Web3 research analyst di Telegram. "
            "Jawab pertanyaan pengguna berdasarkan DATA GMGN yang diberikan. "
            "Gunakan hanya fakta yang tersedia dan tandai inferensi sebagai ANALISIS. "
            "Jangan mengarang angka, wallet, holder, trader, ATH, volume, liquidity, atau transaksi. "
            "Jika sebuah field tidak tersedia, tulis N/A atau 'tidak tersedia'. "
            "Untuk TOKEN, susun laporan dengan urutan: "
            "1) identitas + CA, 2) harga + MC + ATH price + ATH market cap + jarak current MC dari ATH, "
            "3) liquidity + volume 24h + holders, 4) konsentrasi Top 10 holders dalam %, "
            "5) daftar 10 holder terbesar beserta address singkat dan % supply jika tersedia, "
            "6) creator/dev/team holding, 7) smart/renowned/whale/sniper/bundler/fresh wallet stats jika tersedia, "
            "8) security/audit, mint/freeze/owner/creator risk, 9) pool/DEX, "
            "10) top traders dan profit/position metrics jika tersedia, 11) ANALISIS dan data yang perlu dipantau. "
            "Untuk MARKET, jangan membuat Markdown table. Tampilkan setiap token sebagai kartu bernomor dengan "
            "Name/Symbol, MC, ATH MC, current vs ATH, Volume, Liquidity, Holders dan CA. "
            "Untuk WALLET, tampilkan statistik utama lalu aktivitas penting. "
            "Untuk EARLY_WALLET_OVERLAP, jelaskan bahwa 'early' berarti 20 wallet paling awal "
            "berdasarkan start_holding_at dari dataset trader GMGN yang tersedia. "
            "Hanya tampilkan token yang memiliki minimal 3 wallet yang sama. "
            "Untuk setiap token tampilkan jumlah shared wallets, status BUYING/HOLD, short wallet, "
            "dan asal token tempat wallet tersebut terdeteksi early. Jangan mengklaim hold jika data tidak mendukung. "
            "Jika tidak ada token dengan >=3 wallet, katakan tidak ada hasil yang memenuhi filter. "
            "FORMAT TELEGRAM: plain text yang rapi, tanpa Markdown table, tanpa tanda |, tanpa ##, tanpa **, "
            "gunakan emoji dan bullet '•'. Maksimal 3500 karakter. "
            "Jangan memberikan kepastian profit atau instruksi buy/sell. "
            "Pertanyaan pengguna:\n" + request_text +
            "\n\nDATA GMGN:\n" + json.dumps(research_payload, ensure_ascii=False, default=str)
        )
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": request_text},
        ]
        try:
            answer = await self.ask(messages)
            return "🤖 AI GMGN RESEARCH\n━━━━━━━━━━━━━━━━━━━━\n" + answer + "\n\n⚙️ AI: " + (self.last_provider or "unknown")
        except Exception:
            return self._format_fallback(request_text, research_payload)

    @classmethod
    def _format_fallback(cls, request_text: str, payload: dict) -> str:
        if payload.get("mode") == "early_wallet_overlap":
            lines = [
                "🔎 EARLY WALLET OVERLAP",
                "━━━━━━━━━━━━━━━━━━━━",
                f"⛓ Chain: {payload.get('chain', 'N/A').upper()}",
                f"🕒 Window: {payload.get('window_label', 'N/A')}",
                "👛 Rule: 20 wallet paling awal/token",
                "🔗 Filter: minimal 3 wallet yang sama",
                "",
            ]
            overlaps = payload.get("overlaps") or []
            if not overlaps:
                lines.append("Tidak ada hasil yang memenuhi filter minimal 3 wallet.")
            else:
                for i, item in enumerate(overlaps[:10], 1):
                    lines += [
                        f"{i:02d}. {item.get('token') or item.get('symbol') or 'Unknown'}",
                        f"   Shared wallets: {item.get('shared_wallet_count', 0)}",
                        f"   MC: {cls._num(item.get('market_cap'), True)} | ATH MC: {cls._num(item.get('ath_market_cap'), True)}",
                    ]
                    for w in item.get("wallets", [])[:8]:
                        tags = w.get("tags") or []
                        tag = f" | {','.join(tags[:2])}" if tags else ""
                        lines.append(f"   • {w.get('wallet')} — {w.get('status', 'N/A')}{tag}")
                    lines.append("")
            lines.append("⚠️ AI fallback aktif.")
            return "\n".join(lines)

        if payload.get("mode") == "deep_wallet_convergence":
            lines = [
                "🔎 DEEP WALLET CONVERGENCE",
                "━━━━━━━━━━━━━━━━━━━━",
                "⛓ Chain: " + str(payload.get("chain", "N/A")).upper(),
                "🕒 Window: " + str(payload.get("window_label", "N/A")),
                "🎯 Candidates: " + str(payload.get("candidate_count", 0)),
                "👛 Minimum/category: " + str(payload.get("wallet_min_per_category", 20)),
                "",
            ]
            counts = payload.get("category_counts") or {}
            for key, label in (
                ("early_buyers", "Early buyers"),
                ("early_exit", "Early exit"),
                ("top_traders", "Top traders"),
                ("whales", "Whales"),
            ):
                lines.append("• " + label + ": " + str(counts.get(key, 0)))
            lines.append("")
            overlaps = payload.get("final_overlaps") or []
            if not overlaps:
                lines.append("❌ Tidak ada token yang memenuhi overlap minimal 3 wallet.")
            else:
                for i, item in enumerate(overlaps[:10], 1):
                    lines.append(
                        str(i) + ". " + str(item.get("symbol") or item.get("name") or "UNKNOWN")
                        + " — " + str(item.get("wallet_count", 0)) + " wallets"
                    )
                    if item.get("market_cap"):
                        lines.append("   MC: " + cls._num(item.get("market_cap"), True))
                    for w in item.get("wallets", [])[:6]:
                        cats = ",".join(w.get("categories") or [])
                        lines.append("   • " + cls._short_wallet(w.get("source_wallet")) + " — " + str(w.get("status", "N/A")) + " [" + cats + "]")
                    lines.append("")
            if payload.get("rate_limit_or_api_errors"):
                lines.append("⚠️ Sebagian request GMGN gagal/rate-limited; angka tersebut tidak dihitung sebagai zero-match.")
            if payload.get("activity_errors"):
                lines.append("⚠️ " + str(payload.get("activity_errors")) + " wallet activity request gagal.")
            lines.append("ℹ️ BUY/HOLD di workflow ini berbasis event aktivitas terbaru, bukan snapshot holdings exact.")
            return "\n".join(lines)

        if payload.get("mode") == "market_discovery":
            raw = cls._unwrap(payload.get("market_rank", {}))
            rows = raw.get("rank", []) if isinstance(raw, dict) else []
            lines = [
                "🔎 GMGN MARKET RESEARCH",
                "━━━━━━━━━━━━━━━━━━━━",
                f"⛓ Chain: {payload.get('chain', 'N/A').upper()}",
                f"🕒 Window: {payload.get('window_label', 'N/A')}",
                f"📡 Data: {payload.get('interval_used', 'N/A')}",
                f"💰 ATH MC filter: ≥ {cls._num(payload.get('ath_mc_min_usd'), True)}",
                "",
            ]
            for i, coin in enumerate(rows[:10], 1):
                name = coin.get("name") or coin.get("symbol") or "Unknown"
                symbol = coin.get("symbol") or ""
                mc = cls._first(coin, "market_cap", "market_cap_usd", "mc")
                ath = cls._first(coin, "history_highest_market_cap", "ath_market_cap")
                vol = cls._first(coin, "volume_24h", "volume", "volume_usd")
                liq = cls._first(coin, "liquidity", "liquidity_usd")
                lines += [
                    f"{i:02d}. {name} ({symbol})",
                    f"   MC {cls._num(mc, True)} | ATH {cls._num(ath, True)}",
                    f"   Vol {cls._num(vol, True)} | Liq {cls._num(liq, True)}",
                ]
            lines += ["", "⚠️ AI fallback aktif: semua provider AI gagal."]
            return "\n".join(lines)

        token = cls._unwrap(payload.get("token", {}))
        if not isinstance(token, dict):
            token = {}
        name = token.get("name") or token.get("symbol") or "Unknown token"
        symbol = token.get("symbol") or ""
        return "\n".join([
            "🧠 GMGN DEEP RESEARCH",
            "━━━━━━━━━━━━━━━━━━━━",
            f"🪙 {name} ({symbol})",
            f"⛓ Chain: {payload.get('chain', 'N/A').upper()}",
            f"📍 CA: {payload.get('address', 'N/A')}",
            "",
            f"Price: {cls._num(token.get('price'))}",
            f"MC: {cls._num(cls._first(token, 'market_cap', 'market_cap_usd', 'mc'), True)}",
            f"Liquidity: {cls._num(cls._first(token, 'liquidity', 'liquidity_usd'), True)}",
            f"24h Vol: {cls._num(cls._first(token, 'volume_24h', 'volume', 'volume_usd'), True)}",
            "",
            "⚠️ AI fallback aktif. Data GMGN tersedia tetapi synthesis provider gagal.",
        ])

    async def close(self):
        await self.client.aclose()
