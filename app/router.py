import httpx
import json

class AIRouter:
    def __init__(self, settings):
        self.settings = settings
        self.client = httpx.AsyncClient(timeout=45)

    async def plan(self, user_text: str) -> str:
        return user_text

    async def synthesize(self, request_text: str, research_payload) -> str:
        # Prefer Gemini when configured; otherwise return structured GMGN data.
        if self.settings.gemini_api_key:
            prompt = (
                "You are a crypto/Web3 research assistant. Analyze only the supplied GMGN data. "
                "Do not invent missing values. Distinguish observed facts from inference. "
                "Return concise Indonesian with: Summary, key metrics, holders/traders, risks, "
                "and data limitations. User request:\n" + request_text +
                "\n\nGMGN DATA:\n" + json.dumps(research_payload, ensure_ascii=False, default=str)
            )
            url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
            r = await self.client.post(url, params={"key": self.settings.gemini_api_key},
                                       json={"contents":[{"parts":[{"text":prompt}]}]})
            if r.is_success:
                body = r.json()
                try:
                    return body["candidates"][0]["content"]["parts"][0]["text"]
                except (KeyError, IndexError):
                    pass
        return "📊 GMGN DATA\n" + json.dumps(research_payload, ensure_ascii=False, indent=2, default=str)[:3600]

    async def close(self):
        await self.client.aclose()
