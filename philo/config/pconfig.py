import argparse
from pathlib import Path
from typing import Literal
from dataclasses import dataclass, field


@dataclass
class McpEntry:
    name: str
    transportType: Literal["stdio", "sse", "streamableHttp"] | None = None  # auto-detected if omitted
    command: str = ""  # Stdio: command to run (e.g. "npx")
    args: list[str] = field(default_factory=list)  # Stdio: command arguments
    env: dict[str, str] = field(default_factory=dict)  # Stdio: extra env vars
    url: str = ""  # HTTP/SSE: endpoint URL
    headers: dict[str, str] = field(default_factory=dict)  # HTTP/SSE: custom headers
    timeout: int = 30  # seconds before a tool call is cancelled


class PhiloConfig(object):
    def __init__(self, cfgname):
        self.mode = "react"
        self.cfgname = cfgname
        self.nobuf = False
        self.verbose = True
        self.quiet = False
        self.noColor = False
        self.logFile = None
        self.workspace = None
        self.agentSpace = None
        self.llm = None
        self.bus = None
        self.bochaApiKey = None
        self.mcpEntries = []
        self.temperature = 0.5
        self.maxTokens = None  # None means no limit, model default
        self.thinking = None  # None | "disable" | "enabled" | "max"
        self.maxToolIterations = 100
        self.memoryWindow = 100
        self.execTimeout = 60
        self.pathAppends = []

        # Context management
        self.contextWindowRatio = 0.8  # Threshold to trigger context compression
        self.minKeepMessages = 6  # Minimum messages to keep when compressing (system + recent tool pairs + user)
        self.keepRecentToolPairs = 2  # Number of recent assistant+tool pairs to preserve
        self.oneshotInput = None
        self.appId = None
        self.appSecret = None
        self.soul = "You are Philo, a helpful AI research agent."

        # Token pricing (per million tokens)
        self.inputTokenPrice = 4
        self.outputTokenPrice = 18

        # Extra tools and skills (for external injection)
        self.extraTools = []  # List of ToolBase instances
        self.extraSkills = []  # List of skill paths or dicts

    def enrichArgs(self):
        parser = argparse.ArgumentParser()
        parser.add_argument("-nobuf", action="store_true")
        parser.add_argument("-quiet", action="store_true")
        parser.add_argument("-no-color", action="store_true")
        parser.add_argument("-log", dest="logFile", type=str, default=None)
        parser.add_argument("-i", dest="oneshotInput", type=str, default=None)
        args, _ = parser.parse_known_args()
        self.nobuf = args.nobuf
        self.quiet = args.quiet
        self.noColor = args.no_color
        if args.logFile is not None:
            self.logFile = args.logFile
        if args.oneshotInput is not None:
            self.oneshotInput = args.oneshotInput

    def finalize(self):
        if self.mode == "react":
            if self.workspace is None:
                raise ValueError("Workspace not set")
            if isinstance(self.workspace, str):
                self.workspace = Path(self.workspace)
            self.workspace = self.workspace.expanduser()
            self.agentSpace = self.workspace / self.cfgname
            if self.bus is None:
                from philo.infra.bus import MessageBus
                self.bus = MessageBus()
        elif self.mode == "chat":
            # chat mode doesn't need workspace or agentSpace
            pass
        if self.llm is None:
            raise ValueError("Llm not set")
        self.enrichArgs()
        from philo.utils.log import log
        log.verbose = self.verbose and not self.quiet
        if self.logFile is not None:
            log.setLogFile(self.logFile)
        return self
