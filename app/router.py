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

    def _providers(self):
        mapping = {
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

        url = base_url.rstrip("/") + "/chat/completions"
        r = await self.client.post(
            url,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
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
        for name, key, base_url, model in self._providers():
            try:
                answer = await self._call(name, key, base_url, model, messages)
                if answer:
                    self.last_provider = name
                    return answer
            except Exception as exc:
                self.last_errors.append(f"{name}: {str(exc)[:180]}")
        self.last_provider = None
        raise RuntimeError("Tutti AI provider gagal: " + " | ".join(self.last_errors[:5]))

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
            "Gunakan fakta yang tersedia dan tandai inferensi sebagai analisis. "
            "Jangan mengarang angka, wallet, holder, trader, ATH, volume, atau transaksi. "
            "Jika data tidak tersedia, katakan tidak tersedia. "
            "Untuk token bahas market cap, ATH GMGN, volume, liquidity, holder/trader concentration, "
            "smart-money signals, security dan pool jika field tersebut tersedia. "
            "Untuk wallet bahas aktivitas dan statistik yang tersedia. "
            "Untuk market jelaskan alasan kandidat muncul berdasarkan field GMGN. "
            "Jawab dalam bahasa Indonesia, natural seperti AI researcher, bukan JSON dump. "
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
