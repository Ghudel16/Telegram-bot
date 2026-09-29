class AIRouter:
    def __init__(self, settings):
        self.settings = settings

    async def plan(self, user_text: str) -> str:
        return user_text

    async def synthesize(self, request_text: str, research_payload: str) -> str:
        return research_payload
