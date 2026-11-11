from typing import Any
from abc import ABC, abstractmethod
from philo.utils.log import log
from philo.infra.bus import InboundMessage, OutboundMessage, MessageBus


class BaseChannel(ABC):
    def __init__(self, name, bus: MessageBus, allowedIds=None):
        self.name = name
        self.bus = bus
        self.allowedIds = None if allowedIds is None else set(allowedIds)

    @abstractmethod
    async def start(self):
        pass

    @abstractmethod
    async def stop(self):
        pass

    @abstractmethod
    async def send(self, msg: OutboundMessage):
        pass

    async def handleMessage(
        self,
        senderId: str,
        chatId: str,
        content: str,
        files: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if self.allowedIds is not None and senderId not in self.allowedIds:
            log.red("Access denied for sender {} on channel {}", senderId, self.name)
            return
        msg = InboundMessage(
            channel=self.name,
            senderId=str(senderId),
            chatId=str(chatId),
            content=content,
            files=files or [],
            metadata=metadata or {},
        )
        await self.bus.writeInbound(msg)
