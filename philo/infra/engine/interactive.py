import asyncio
from philo.utils.log import log
from philo.config.pconfig import PhiloConfig
from philo.infra.bus import InboundMessage
from philo.infra.engine.base import PhiloEngineBase
from philo.tools.askuser import AskUserTool


class PhiloInteractiveEngine(PhiloEngineBase):
    def __init__(self, pcfg: PhiloConfig):
        super().__init__(pcfg)
        self.channel = "cli"
        self.senderId = "user"
        self.chatId = self.pcfg.cfgname
        self.askingUser = False
        self.activeStatus = None
        self.loop.toolManager.register(AskUserTool(self.askUser))

    def setupLogging(self):
        if self.pcfg.logFile is not None:
            return
        logDir = self.pcfg.agentSpace / "logs"
        logDir.mkdir(parents=True, exist_ok=True)
        self.pcfg.logFile = str(logDir / "interactive.log")
        log.setLogFile(self.pcfg.logFile)

    async def askUser(self, question: str) -> str:
        self.askingUser = True
        status = self.activeStatus
        if status is not None:
            status.stop()
        try:
            self.cli.flushPendingTtyInput()
            self.cli.print(f"\n[bold yellow]Philo asks:[/bold yellow] {question}")
            return await self.cli.readInteractiveInput()
        finally:
            self.askingUser = False
            if status is not None:
                status.start()

    async def runInteractive(self):
        self.setupLogging()
        log.cyan("Philo running interactively")
        self.cli.print(f"[dim]Logs: {self.pcfg.logFile}[/dim]")
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
                self.activeStatus = status
                stopUpdate = False

                async def updateThinkingStatus():
                    with status:
                        while not stopUpdate:
                            try:
                                if not self.askingUser:
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
                    self.activeStatus = None

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
