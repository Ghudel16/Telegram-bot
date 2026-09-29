import httpx

class GMGNClient:
    def __init__(self, settings):
        self.key = settings.gmgn_api_key
        self.base_url = settings.gmgn_base_url
        self.client = httpx.AsyncClient(timeout=30)

    async def request(self, method: str, path: str, **kwargs):
        if not self.base_url:
            raise RuntimeError('GMGN_BASE_URL belum dikonfigurasi.')
        headers = kwargs.pop('headers', {})
        if self.key:
            headers['Authorization'] = f'Bearer {self.key}'
            headers['X-API-Key'] = self.key
        response = await self.client.request(method, self.base_url.rstrip('/') + '/' + path.lstrip('/'), headers=headers, **kwargs)
        response.raise_for_status()
        return response.json()

    async def close(self):
        await self.client.aclose()
