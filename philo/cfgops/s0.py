import os


def llm():
    from philo.llm.openai import PhiloOpenAiLlm
    return PhiloOpenAiLlm(
        modelName="deepseek-v4-flash",
        contextWindow=1048576,
        # modelName="glm-5-fp8",
        # contextWindow=202752,
        url="http://192.168.1.13:18173/v1",
        apiKey=os.getenv("LOCAL_API_KEY"),
        maxRetry=None,
    )


def mcps():
    from philo.config.pconfig import McpEntry
    return [
        # McpEntry(
        #     name="bocha-mcp",
        #     transportType="streamableHttp",
        #     url="https://mcp.bochaai.com/mcp",
        #     headers={
        #         "Authorization": "Bearer {}".format(bochaApiKey()),
        #     },
        #     timeout=300,
        # )
    ]


def name():
    return "server0"


def pcfg():
    from philo.config.pconfig import PhiloConfig
    pcfg = PhiloConfig(name())
    pcfg.workspace = "/z5s/ame/x/philo"
    pcfg.llm = llm()
    pcfg.mcpEntries = mcps()
    pcfg.appId = os.getenv("BOT0_APPID")
    pcfg.appSecret = os.getenv("BOT0_APPSECRET")
    return pcfg


def main():
    import asyncio
    from philo.infra.engine.server import PhiloServerEngine
    engine = PhiloServerEngine(pcfg=pcfg())
    asyncio.run(engine.runServer())


if __name__ == "__main__":
    main()
