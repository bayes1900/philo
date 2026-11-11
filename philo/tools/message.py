from typing import Any
from philo.utils.log import log
from philo.tools.base import ToolBase
from philo.infra.bus import OutboundMessage, MessageBus


class MessageTool(ToolBase):
    def __init__(self, bus: MessageBus):
        self.bus = bus

    @property
    def name(self) -> str:
        return "message"

    @property
    def description(self) -> str:
        return "Send a message to the user. Use this when you want to communicate something."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The message content to send"
                },
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional: list of file paths to attach (images, documents)"
                }
            },
            "required": ["content"]
        }

    async def execute(self, content, files=None, **kwargs) -> str:
        if "context" not in kwargs:
            errMsg = "Error: Context not set for message tool"
            log.red(errMsg)
            return errMsg

        channel = kwargs["context"]["channel"]
        chatId = kwargs["context"]["chatId"]
        messageId = kwargs["context"]["messageId"]

        msg = OutboundMessage(
            channel=channel,
            chatId=chatId,
            content=content,
            media=files or [],
            metadata={
                "message_id": messageId,
            },
        )
        try:
            await self.bus.writeOutbound(msg)
            mediaInfo = f" with {len(files)} attachments" if files else ""
            return f"Message sent to {channel}:{chatId}{mediaInfo}"
        except Exception as e:
            return f"Error sending message: {str(e)}"
