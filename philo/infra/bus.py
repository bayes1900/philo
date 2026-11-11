import asyncio
from typing import Any
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class InboundMessage:
    channel: str
    senderId: str
    chatId: str
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    files: list[str] = field(default_factory=list)  # File URLs
    metadata: dict[str, Any] = field(default_factory=dict)  # Channel-specific data

    @property
    def sessionId(self) -> str:
        return f"{self.channel}:{self.chatId}"


@dataclass
class OutboundMessage:
    channel: str
    chatId: str
    content: str
    replyTo: str | None = None
    media: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


MAX_QUEUE_SIZE = 10000

class MessageBus:
    def __init__(self):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)

    async def writeInbound(self, msg: InboundMessage) -> None:
        await self.inbound.put(msg)

    async def readInbound(self) -> InboundMessage:
        return await self.inbound.get()

    async def writeOutbound(self, msg: OutboundMessage) -> None:
        await self.outbound.put(msg)

    async def readOutbound(self) -> OutboundMessage:
        return await self.outbound.get()

    @property
    def inboundSize(self) -> int:
        return self.inbound.qsize()

    @property
    def outboundSize(self) -> int:
        return self.outbound.qsize()
