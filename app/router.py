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
    def _num(value: Any) -> str:
        if value is None:
            return "-"
        try:
            n = float(value)
            if abs(n) >= 1_000_000_000:
                return "\$" + f"{n/1_000_000_000:.2f}B"
            if abs(n) >= 1_000_000:
                return "\$" + f"{n/1_000_000:.2f}M"
            if abs(n) >= 1_000:
                return "\$" + f"{n/1_000:.2f}K"
            return f"{n:.6g}"
        except (TypeError, ValueError):
            return str(value)

    @classmethod
    def _format_fallback(cls, request_text: str, payload: dict) -> str:
        mode = payload.get("mode")

        if mode == "market_discovery":
            raw = payload.get("market_rank", {})
            data = cls._unwrap(raw)
            rows = data.get("rank", []) if isinstance(data, dict) else []
            rows = rows[:15]

            lines = [
                "🔎 GMGN MARKET RESEARCH",
                f"Chain: {payload.get('chain', '-')}",
                f"Window: {payload.get('requested_window_hours', 0)} jam",
                f"Interval data: {payload.get('interval_used', '-')}",
                f"Filter MC: >= {cls._num(payload.get('ath_mc_min_usd'))}",
                "",
                "📊 TOP MARKET",
            ]

            if not rows:
                lines.append("Tidak ada data market yang dikembalikan GMGN.")
            else:
                for i, coin in enumerate(rows, 1):
                    name = coin.get("name") or coin.get("symbol") or "Unknown"
                    symbol = coin.get("symbol", "")
                    price = cls._num(coin.get("price"))
                    change = coin.get("price_change_percent")
                    mc = coin.get("market_cap") or coin.get("market_cap_usd") or coin.get("fdv")
                    if isinstance(change, (int, float)):
                        change_text = f"{change:+.2f}%"
                    elif change is not None:
                        change_text = str(change)
                    else:
                        change_text = "-"
                    lines.append(
                        f"{i}. {name} ({symbol}) | {price} | {change_text} | MC {cls._num(mc)}"
                    )

            lines += [
                "",
                "⚠️ Catatan:",
                "Data di atas adalah ranking market GMGN pada interval yang tersedia, bukan bukti historis ATH MC.",
                "Untuk deep research token, kirim contract address (CA).",
            ]
            return "\n".join(lines)

        token = payload.get("token", {})
        token_data = cls._unwrap(token)
        if not isinstance(token_data, dict):
            token_data = {}

        name = token_data.get("name") or token_data.get("symbol") or "Unknown token"
        symbol = token_data.get("symbol", "")
        price = token_data.get("price")
        mc = token_data.get("market_cap") or token_data.get("market_cap_usd") or token_data.get("fdv")
        liquidity = token_data.get("liquidity") or token_data.get("liquidity_usd")

        lines = [
            "🧠 GMGN DEEP RESEARCH",
            f"Token: {name} ({symbol})",
            f"Chain: {payload.get('chain', '-')}",
            f"CA: {payload.get('address', '-')}",
            "",
            "📌 METRICS",
            f"Price: {cls._num(price)}",
            f"Market Cap/FDV: {cls._num(mc)}",
            f"Liquidity: {cls._num(liquidity)}",
            "",
            "🔐 SECURITY / HOLDERS / TRADERS",
            "Data GMGN berhasil diambil. Untuk detail lengkap, analisis AI akan digunakan bila provider AI tersedia.",
            "",
            "⚠️ Ini analisis data, bukan instruksi trading.",
        ]
        return "\n".join(lines)

    async def synthesize(self, request_text: str, research_payload) -> str:
        if self.settings.gemini_api_key:
            prompt = (
                "You are a crypto/Web3 research assistant. Analyze only the supplied GMGN data. "
                "Do not invent missing values. Distinguish observed facts from inference. "
                "Return concise Indonesian plain text, suitable for Telegram, with these sections: "
                "Kesimpulan, Data utama, Holder/Trader, Risiko, dan Keterbatasan data. "
                "Never output raw JSON and never prefix the answer with 'GMGN DATA'. "
                "User request:\n" + request_text +
                "\n\nGMGN DATA:\n" + json.dumps(research_payload, ensure_ascii=False, default=str)
            )
            try:
                url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
                r = await self.client.post(
                    url,
                    params={"key": self.settings.gemini_api_key},
                    json={"contents": [{"parts": [{"text": prompt}]}]},
                )
                if r.is_success:
                    body = r.json()
                    text = body["candidates"][0]["content"]["parts"][0]["text"].strip()
                    if text:
                        return text
            except Exception:
                pass

        return self._format_fallback(request_text, research_payload)

    async def close(self):
        await self.client.aclose()
