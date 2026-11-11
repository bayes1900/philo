import asyncio
from philo.utils.log import log
from philo.config.pconfig import PhiloConfig
from philo.infra.bus import InboundMessage
from philo.infra.engine.base import PhiloEngineBase


class PhiloOneshotEngine(PhiloEngineBase):
    def __init__(self, pcfg: PhiloConfig):
        super().__init__(pcfg)
        self.channel = "cli"
        self.senderId = "oneshot"
        self.chatId = self.pcfg.cfgname
        if self.pcfg.oneshotInput is None or len(self.pcfg.oneshotInput) == 0:
            raise ValueError("Oneshot input not set")

    async def runOneshot(self):
        brief = self.pcfg.oneshotInput if len(self.pcfg.oneshotInput) <= 50 else "{}...".format(self.pcfg.oneshotInput[:50])
        log.cyan("Philo running oneshot: [{}]".format(brief))

        inboundTask = asyncio.create_task(self.runInboundLoop())
        outboundTask = asyncio.create_task(self.runOutboundLoop())
        self.asyncTasks.append(inboundTask)
        self.asyncTasks.append(outboundTask)
        self.ready4Input.set()

        try:
            self.ready4Input.clear()
            self.agentResponseList.clear()
            await self.bus.writeInbound(InboundMessage(
                channel=self.channel,
                senderId=self.senderId,
                chatId=self.chatId,
                content=self.pcfg.oneshotInput,
            ))
            # Create thinking status with real-time token updates
            status = self.cli.createThinkingStatus()
            stopUpdate = False

            async def updateThinkingStatus():
                with status:
                    while not stopUpdate:
                        try:
                            stats = self.loop.getTokenUsageStats()
                            status.update(self.cli.buildThinkingStatusText(stats))
                            await asyncio.sleep(0.3)
                        except Exception:
                            await asyncio.sleep(0.3)

            updateTask = asyncio.create_task(updateThinkingStatus())
            try:
                await self.ready4Input.wait()
            finally:
                stopUpdate = True
                updateTask.cancel()
                try:
                    await updateTask
                except asyncio.CancelledError:
                    pass

            for item in self.agentResponseList:
                self.cli.renderMarkdown(item)
            stats = self.loop.getTokenUsageStats()
            self.cli.displayTokenUsageInline(stats)

        except KeyboardInterrupt:
            self.cli.restoreTerminal()
            self.cli.print("\nGoodbye!")
        except EOFError:
            self.cli.restoreTerminal()
            self.cli.print("\nGoodbye!")
        finally:
            await self.loop.mcpManager.disconnect()
            for task in self.asyncTasks:
                task.cancel()
