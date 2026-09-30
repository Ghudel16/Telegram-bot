import httpx
import json
from typing import Any


class AIRouter:
    def __init__(self, settings):
        self.settings = settings
        self.client = httpx.AsyncClient(timeout=45)

    async def plan(self, user_text: str) -> str:
        return user_text

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

    @classmethod
    def _format_fallback(cls, request_text: str, payload: dict) -> str:
        if payload.get("mode") == "market_discovery":
            raw = cls._unwrap(payload.get("market_rank", {}))
            rows = raw.get("rank", []) if isinstance(raw, dict) else []
            rows = rows[:10]

            lines = [
                "🔎 GMGN MARKET RESEARCH",
                "━━━━━━━━━━━━━━━━━━━━",
                f"⛓ Chain      : {payload.get('chain', 'N/A').upper()}",
                f"🕒 Window     : {payload.get('window_label', str(payload.get('requested_window_hours', 0)) + ' jam')}",
                f"📡 Data       : {payload.get('interval_used', 'N/A')}",
                f"💰 MC filter  : ≥ {cls._num(payload.get('ath_mc_min_usd'), money=True)}",
                "",
                "📊 MARKET SNAPSHOT",
            ]

            if not rows:
                lines.append("Tidak ada market yang dikembalikan GMGN.")
            else:
                for i, coin in enumerate(rows, 1):
                    name = coin.get("name") or coin.get("symbol") or "Unknown"
                    symbol = coin.get("symbol") or ""
                    price = cls._num(coin.get("price"))
                    change = cls._change(coin.get("price_change_percent"))
                    mc = cls._first(coin, "market_cap", "market_cap_usd", "mc")
                    ath = cls._first(coin, "history_highest_market_cap", "ath_market_cap")
                    vol = cls._first(coin, "volume_24h", "volume", "volume_usd")
                    liq = cls._first(coin, "liquidity", "liquidity_usd")
                    extra = []
                    if mc is not None:
                        extra.append("MC " + cls._num(mc, money=True))
                    if ath is not None:
                        extra.append("ATH " + cls._num(ath, money=True))
                    if vol is not None:
                        extra.append("Vol " + cls._num(vol, money=True))
                    if liq is not None:
                        extra.append("Liq " + cls._num(liq, money=True))
                    stats = " • ".join(extra) if extra else "MC/Vol/Liq N/A"
                    lines.extend([
                        f"{i:02d}  {name} ({symbol})",
                        f"    💵 {price}   📈 {change}",
                        f"    {stats}",
                    ])

            lines += [
                "",
                "⚠️ DATA NOTE",
                "Ranking yang diterima adalah snapshot GMGN pada interval data yang tersedia.",
                "Filter ATH ≥ MC menggunakan field history_highest_market_cap GMGN.",
                "Untuk 7/30 hari, window menentukan umur token yang dicari; ATH yang ditampilkan adalah ATH all-time GMGN, bukan ATH khusus window.",
                "",
                "🧠 Untuk deep research token: kirim CA (contract address).",
            ]
            return "\n".join(lines)

        token = cls._unwrap(payload.get("token", {}))
        if not isinstance(token, dict):
            token = {}

        name = token.get("name") or token.get("symbol") or "Unknown token"
        symbol = token.get("symbol") or ""
        price = token.get("price")
        mc = cls._first(token, "market_cap", "market_cap_usd", "mc")
        fdv = cls._first(token, "fdv", "fully_diluted_valuation")
        liq = cls._first(token, "liquidity", "liquidity_usd")
        vol = cls._first(token, "volume_24h", "volume", "volume_usd")

        return "\n".join([
            "🧠 GMGN DEEP RESEARCH",
            "━━━━━━━━━━━━━━━━━━━━",
            f"🪙 {name} ({symbol})",
            f"⛓ Chain : {payload.get('chain', 'N/A').upper()}",
            f"📍 CA    : {payload.get('address', 'N/A')}",
            "",
            "📌 KEY METRICS",
            f"Price    : {cls._num(price)}",
            f"Market Cap: {cls._num(mc, money=True)}",
            f"FDV      : {cls._num(fdv, money=True)}",
            f"Liquidity: {cls._num(liq, money=True)}",
            f"24h Vol  : {cls._num(vol, money=True)}",
            "",
            "👥 HOLDERS / TRADERS",
            "GMGN holder dan trader data berhasil diambil.",
            "AI synthesis akan ditampilkan bila provider AI berhasil merespons.",
            "",
            "⚠️ Risk note: data ini adalah riset on-chain, bukan instruksi trading.",
        ])

    async def synthesize(self, request_text: str, research_payload) -> str:
        if self.settings.gemini_api_key:
            prompt = (
                "You are a crypto/Web3 research assistant. Analyze only the supplied GMGN data. "
                "Do not invent missing values. Distinguish observed facts from inference. "
                "Write concise Indonesian suitable for Telegram. Use clean headings and bullets: "
                "Kesimpulan, Data Utama, Holder/Trader, Risiko, Keterbatasan Data. "
                "Do not output JSON. Do not repeat the entire raw payload. "
                "Do not give fabricated ATH values. "
                "User request:\n" + request_text +
                "\n\nGMGN DATA:\n" + json.dumps(research_payload, ensure_ascii=False, default=str)
            )
            try:
                url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
                response = await self.client.post(
                    url,
                    params={"key": self.settings.gemini_api_key},
                    json={"contents": [{"parts": [{"text": prompt}]}]},
                )
                if response.is_success:
                    body = response.json()
                    answer = body["candidates"][0]["content"]["parts"][0]["text"].strip()
                    if answer:
                        return answer
            except Exception:
                pass

        return self._format_fallback(request_text, research_payload)

    async def close(self):
        await self.client.aclose()
