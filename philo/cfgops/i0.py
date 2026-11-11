import os
import sys
from pathlib import Path


def llm():
    from philo.llm.openai import PhiloOpenAiLlm
    return PhiloOpenAiLlm(
        modelName="deepseek-v4.1-flash",
        contextWindow=1048576,
        url="http://192.168.1.13:18173/v1",
        apiKey=os.getenv("LOCAL_API_KEY"),
        maxRetry=None,
    )


def skills():
    return ["/sandbox/ame/workspace/tmp/skills/novel-writer-cn"]


def mcps():
    from philo.config.pconfig import McpEntry
    return [
        McpEntry(
            name="deepseek-search",
            transportType="stdio",
            command=sys.executable or "python3",
            args=[str(Path(__file__).resolve().parents[1] / "manual" / "dsmcp.py")],
            env={"DEEPSEEK_API_KEY": os.getenv("DEEPSEEK_API_KEY", "")},
            timeout=120,
        )
    ]


def name():
    return "inter0"


def pcfg():
    from philo.config.pconfig import PhiloConfig
    pcfg = PhiloConfig(name())
    pcfg.workspace = "/z5s/ame/x/philo"
    pcfg.llm = llm()
    pcfg.mcpEntries = mcps()
    pcfg.extraSkills = skills()
    return pcfg


def main():
    import asyncio
    from philo.infra.engine.interactive import PhiloInteractiveEngine
    engine = PhiloInteractiveEngine(pcfg=pcfg())
    asyncio.run(engine.runInteractive())


if __name__ == "__main__":
    main()
