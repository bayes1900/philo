import asyncio
from philo.utils.log import log
from philo.config.pconfig import PhiloConfig
from philo.infra.bus import InboundMessage
from philo.infra.engine.base import PhiloEngineBase


class PhiloInteractiveEngine(PhiloEngineBase):
    def __init__(self, pcfg: PhiloConfig):
        super().__init__(pcfg)
        self.channel = "cli"
        self.senderId = "user"
        self.chatId = self.pcfg.cfgname

    async def runInteractive(self):
        log.cyan("Philo running interactively")
        self.cli.initPromptSession()
        inboundTask = asyncio.create_task(self.runInboundLoop())
        outboundTask = asyncio.create_task(self.runOutboundLoop())
        self.asyncTasks.append(inboundTask)
        self.asyncTasks.append(outboundTask)
        self.ready4Input.set()

        while True:
            try:
                self.cli.flushPendingTtyInput()
                userInput = await self.cli.readInteractiveInput()
                if userInput is None or len(userInput) == 0:
                    continue
                if userInput == "/stop":
                    self.cli.print("\nGoodbye!")
                    break
                self.ready4Input.clear()
                self.agentResponseList.clear()
                await self.bus.writeInbound(InboundMessage(
                    channel=self.channel,
                    senderId=self.senderId,
                    chatId=self.chatId,
                    content=userInput,
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
                # Display compact token usage summary
                stats = self.loop.getTokenUsageStats()
                self.cli.displayTokenUsageInline(stats)

            except KeyboardInterrupt:
                self.cli.restoreTerminal()
                self.cli.print("\nGoodbye!")
                break
            except EOFError:
                self.cli.restoreTerminal()
                self.cli.print("\nGoodbye!")
                break

        await self.loop.mcpManager.disconnect()
        for task in self.asyncTasks:
            task.cancel()
