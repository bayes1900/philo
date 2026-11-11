import os
import sys
from pathlib import Path


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


def oneshot():
    return "帮我生成一份类似《三体》的小说，放在工作目录下"


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



def pcfg():
    from philo.config.pconfig import PhiloConfig
    pcfg = PhiloConfig("oneshot0")
    pcfg.workspace = "/z5s/ame/x/philo"
    pcfg.llm = llm()
    pcfg.oneshotInput = oneshot()
    pcfg.mcpEntries = mcps()
    pcfg.extraSkills = skills()
    return pcfg


def main():
    import asyncio
    from philo.infra.engine.oneshot import PhiloOneshotEngine
    engine = PhiloOneshotEngine(pcfg=pcfg())
    asyncio.run(engine.runOneshot())


if __name__ == "__main__":
    main()
