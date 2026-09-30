import time
import uuid
import httpx

class GMGNClient:
    def __init__(self, settings):
        self.key = settings.gmgn_api_key
        self.base_url = (settings.gmgn_base_url or "https://openapi.gmgn.ai").rstrip("/")
        self.client = httpx.AsyncClient(timeout=30, headers={"User-Agent": "telegram-gmgn-research-bot/1.0"})

    def _auth(self):
        if not self.key:
            raise RuntimeError("GMGN_API_KEY belum dikonfigurasi di Railway.")
        return {"timestamp": str(int(time.time())), "client_id": str(uuid.uuid4())}

    async def request(self, method: str, path: str, params=None, json=None):
        query = dict(params or {})
        query.update(self._auth())
        headers = {"X-APIKEY": self.key, "Content-Type": "application/json"}
        response = await self.client.request(
            method, f"{self.base_url}/{path.lstrip('/')}",
            params=query, headers=headers, json=json
        )
        try:
            payload = response.json()
        except Exception:
            response.raise_for_status()
            raise RuntimeError(f"GMGN returned non-JSON HTTP {response.status_code}")
        if response.status_code >= 400 or payload.get("code") not in (0, "0", None):
            raise RuntimeError(
                f"GMGN API error HTTP {response.status_code}: "
                f"{payload.get('error') or payload.get('message') or payload}"
            )
        return payload.get("data", payload)

    async def token_info(self, chain, address):
        return await self.request("GET", "/v1/token/info", {"chain": chain, "address": address})

    async def token_security(self, chain, address):
        return await self.request("GET", "/v1/token/security", {"chain": chain, "address": address})

    async def token_pool(self, chain, address):
        return await self.request("GET", "/v1/token/pool_info", {"chain": chain, "address": address})

    async def top_holders(self, chain, address, limit=30):
        return await self.request("GET", "/v1/market/token_top_holders",
                                  {"chain": chain, "address": address, "limit": limit})

    async def top_traders(self, chain, address, limit=30):
        return await self.request("GET", "/v1/market/token_top_traders",
                                  {
                                      "chain": chain,
                                      "address": address,
                                      "limit": min(int(limit), 100),
                                      "order_by": "amount_percentage",
                                      "direction": "desc",
                                  })

    async def wallet_activity(self, chain, wallet, limit=50):

        return await self.request("GET", "/v1/user/wallet_activity",
                                  {"chain": chain, "wallet_address": wallet, "limit": limit})

    async def wallet_stats(self, chain, wallet, period="7d"):
        return await self.request("GET", "/v1/user/wallet_stats",
                                  {"chain": chain, "wallet_address": wallet, "period": period})

    async def rank(self, chain="sol", interval="24h", limit=50, order_by="volume",
                   min_history_highest_market_cap=None, max_created=None, min_market_cap=None):
        params = {
            "chain": chain,
            "interval": interval,
            "limit": limit,
            "order_by": order_by,
            "direction": "desc",
        }
        if min_history_highest_market_cap is not None:
            params["min_history_highest_market_cap"] = min_history_highest_market_cap
        if max_created:
            params["max_created"] = max_created
        if min_market_cap is not None:
            params["min_marketcap"] = min_market_cap
        return await self.request("GET", "/v1/market/rank", params)

    async def user_info(self):
        return await self.request("GET", "/v1/user/info")

    async def close(self):
        await self.client.aclose()
