import sys
import signal
import asyncio
from philo.utils.log import log
from philo.config.pconfig import PhiloConfig
from philo.agent.loop import PhiloLoop
from philo.infra.bus import MessageBus, InboundMessage, OutboundMessage
from philo.infra.cli import PhiloCli


class PhiloEngineBase(object):
    def __init__(self, pcfg: PhiloConfig):
        self.pcfg = pcfg.finalize()
        self.bus: MessageBus = self.pcfg.bus
        self.loop = PhiloLoop(self.pcfg)
        self.cli = PhiloCli(self.pcfg)
        self.processingLock = asyncio.Lock()
        self.ready4Input = asyncio.Event()
        self.agentResponseList = []
        self.asyncTasks = []
        self.running = False

    def handleSignal(self, signum, frame):
        sigName = signal.Signals(signum).name
        self.cli.restoreTerminal()
        self.cli.print(f"\nReceived {sigName}, goodbye!")
        sys.exit(0)

    def stop(self):
        self.running = False
        log.inf("Philo client engine stopping")

    async def sendProgress(self, message: InboundMessage, content, toolHint=False, reasoning=False):
        meta = dict(message.metadata or {})
        meta["progress"] = True
        meta["toolHint"] = toolHint
        meta["reasoning"] = reasoning
        await self.bus.writeOutbound(OutboundMessage(
            channel=message.channel,
            chatId=message.chatId,
            content=content,
            metadata=meta,
        ))

    async def dispatch(self, msg: InboundMessage):
        async with self.processingLock:
            try:
                await self.loop.mcpManager.checkConnection()
                response = await self.loop.processMessage(msg, onProgressCallback=self.sendProgress)
                if response is not None:
                    await self.bus.writeOutbound(response)
            except asyncio.CancelledError:
                log.inf("Task cancelled for session {}", msg.sessionId)
                raise
            except Exception as e:
                log.red("Error processing message for session {}", msg.sessionId)
                import traceback; traceback.print_exc()
                await self.bus.writeOutbound(OutboundMessage(
                    channel=msg.channel,
                    chatId=msg.chatId,
                    content="Error encountered: {}".format(e),
                ))

    async def runInboundLoop(self):
        self.running = True
        await self.loop.mcpManager.checkConnection()

        while self.running:
            try:
                msg = await asyncio.wait_for(self.bus.readInbound(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            else:
                await self.dispatch(msg)

    async def runOutboundLoop(self):
        while self.running:
            try:
                msg = await asyncio.wait_for(self.bus.readOutbound(), timeout=1.0)
                if msg.metadata.get("progress"):
                    if getattr(self, "askingUser", False):
                        continue
                    if msg.metadata.get("reasoning"):
                        self.cli.print(f"  [italic bright_white on default]💭 {msg.content}[/italic bright_white on default]")
                    else:
                        self.cli.print(f"  [dim]↳ {msg.content}[/dim]")
                elif not self.ready4Input.is_set():
                    if msg.content:
                        self.agentResponseList.append(msg.content)
                    self.ready4Input.set()
                elif msg.content:
                    if msg.metadata and msg.metadata.get("reasoningContent"):
                        self.cli.print(f"  [italic bright_white on default]💭 {msg.metadata['reasoningContent']}[/italic bright_white on default]")
                    self.cli.renderMarkdown(msg.content)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
