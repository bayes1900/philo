import asyncio
from philo.utils.log import log
from philo.config.pconfig import PhiloConfig
from philo.infra.bus import OutboundMessage
from philo.infra.engine.base import PhiloEngineBase
from philo.infra.channels.feishu import FeishuChannel


class PhiloServerEngine(PhiloEngineBase):
    def __init__(self, pcfg: PhiloConfig):
        super().__init__(pcfg)
        self.channel = "feishu"
        self.appId = pcfg.appId
        self.appSecret = pcfg.appSecret
        self.feishuChannel: FeishuChannel | None = None

    async def runServer(self):
        log.cyan("Philo server starting with Feishu channel")
        self.feishuChannel = FeishuChannel(
            root=self.pcfg.agentSpace,
            appId=self.appId,
            appSecret=self.appSecret,
            bus=self.bus,
        )
        # Start the inbound and outbound processing loops
        inboundTask = asyncio.create_task(self.runInboundLoop())
        outboundTask = asyncio.create_task(self.runFeishuOutboundLoop())
        self.asyncTasks.append(inboundTask)
        self.asyncTasks.append(outboundTask)

        log.inf("Starting Feishu channel...")
        try:
            # Start Feishu channel (this will block until stopped)
            await self.feishuChannel.start()
        except asyncio.CancelledError:
            log.inf("Server task cancelled")
        finally:
            await self.shutdown()

    async def runFeishuOutboundLoop(self):
        while self.running:
            try:
                msg = await asyncio.wait_for(self.bus.readOutbound(), timeout=1.0)
                if self.feishuChannel and msg.content:
                    await self.feishuChannel.send(msg)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.red("Error in Feishu outbound loop: {}", e)

    async def shutdown(self):
        log.inf("Shutting down Philo server...")
        if self.feishuChannel:
            await self.feishuChannel.stop()
        await self.loop.mcpManager.disconnect()
        for task in self.asyncTasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        log.inf("Philo server stopped")
