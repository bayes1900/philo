import asyncio
from openai import AsyncOpenAI


class PhiloEmbedding:
    MAX_RETRY = 3

    def __init__(self, model, baseUrl, apiKey="", maxRetry=None):
        self.model = model
        self.client = AsyncOpenAI(
            api_key=apiKey,
            base_url=baseUrl,
        )
        self.maxRetry = maxRetry if maxRetry is not None else self.MAX_RETRY
        self._dimension = None

    async def embed(self, texts):
        if isinstance(texts, str):
            texts = [texts]

        lastError = None
        for _ in range(max(self.maxRetry, 1)):
            try:
                response = await self.client.embeddings.create(
                    model=self.model,
                    input=texts,
                )
                return [item.embedding for item in response.data]
            except asyncio.CancelledError:
                raise
            except Exception as e:
                lastError = e
                await asyncio.sleep(1)

        if lastError is not None:
            raise lastError
        raise RuntimeError("Embedding failed: maxRetry must be >= 1")

    async def embedOne(self, text):
        result = await self.embed(text)
        return result[0] if result else None

    async def getDimension(self):
        if self._dimension is not None:
            return self._dimension
        vector = await self.embedOne("test")
        self._dimension = len(vector) if vector is not None else 0
        return self._dimension