import os
import sys
import select
from pathlib import Path
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.formatted_text import HTML
from rich.console import Console
from rich.markdown import Markdown


class PhiloCli(object):
    def __init__(self, pcfg):
        self.pcfg = pcfg
        self.cliDir: Path = self.pcfg.agentSpace / "cli"
        self.cliDir.mkdir(parents=True, exist_ok=True)
        self.cliHistoryFile = self.cliDir / pcfg.cfgname
        colorSystem = None if getattr(pcfg, "noColor", False) else "auto"
        self.console = Console(highlight=False, color_system=colorSystem)
        self.promptSession = None
        self.savedTermiosAttrs = None

    def initPromptSession(self):
        try:
            import termios
            self.savedTermiosAttrs = termios.tcgetattr(sys.stdin.fileno())
        except Exception:
            pass
        self.promptSession = PromptSession(
            history=FileHistory(str(self.cliHistoryFile)),
            enable_open_in_editor=False,
            multiline=False,
        )

    def restoreTerminal(self):
        if self.savedTermiosAttrs is None:
            return
        try:
            import termios
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self.savedTermiosAttrs)
        except Exception:
            pass

    def flushPendingTtyInput(self):
        try:
            fd = sys.stdin.fileno()
            if not os.isatty(fd):
                return
        except Exception:
            return
        try:
            import termios
            termios.tcflush(fd, termios.TCIFLUSH)
            return
        except Exception:
            pass
        try:
            while True:
                ready, _, _ = select.select([fd], [], [], 0)
                if not ready:
                    break
                if not os.read(fd, 4096):
                    break
        except Exception:
            return

    def print(self, content):
        self.console.print(content)

    def renderMarkdown(self, content):
        if content is None:
            content = "(empty)"
        body = Markdown(content)
        self.console.print()
        self.console.print(f"[cyan]Philo[/cyan]")
        self.console.print(body)
        self.console.print()

    def thinkingContext(self):
        return self.console.status("[dim]Philo is thinking...[/dim]", spinner="dots")

    def buildThinkingStatusText(self, stats):
        """Build status text for thinking spinner with token stats."""
        if stats is None or stats.get("totalTokens", 0) == 0:
            return "[dim]Philo is thinking...[/dim]"

        totalTokens = f"{stats['totalTokens']:,}"
        totalCost = stats['totalCost']

        # Format cost
        if totalCost == 0:
            costStr = "$0.00"
        elif totalCost < 0.01:
            costStr = f"${totalCost:.6f}"
        else:
            costStr = f"${totalCost:.4f}"

        # Context usage
        ctxInfo = ""
        if stats.get('contextWindow', 0) > 0:
            ctxPercent = stats.get('maxContextUsagePercent', 0)
            if ctxPercent >= 90:
                ctxColor = "red"
            elif ctxPercent >= 70:
                ctxColor = "yellow"
            else:
                ctxColor = "green"
            ctxInfo = f" | [{ctxColor}]ctx: {ctxPercent:.0f}%[/{ctxColor}]"

        return f"[dim]Philo is thinking...[/dim] [cyan]{totalTokens}[/cyan] tokens [dim]{costStr}[/dim]{ctxInfo}"

    def createThinkingStatus(self):
        """Create a status spinner for thinking state. Use with 'with' statement."""
        return self.console.status("[dim]Philo is thinking...[/dim]", spinner="dots")

    def displayTokenUsageInline(self, stats):
        """Display a compact single-line token usage summary."""
        if stats is None or stats.get("totalTokens", 0) == 0:
            return

        totalTokens = f"{stats['totalTokens']:,}"
        totalCost = stats['totalCost']

        if totalCost == 0:
            costStr = "$0.00"
        elif totalCost < 0.01:
            costStr = f"${totalCost:.6f}"
        else:
            costStr = f"${totalCost:.4f}"

        # Context usage
        ctxInfo = ""
        if stats.get('contextWindow', 0) > 0:
            ctxPercent = stats.get('maxContextUsagePercent', 0)
            if ctxPercent >= 90:
                ctxColor = "red"
            elif ctxPercent >= 70:
                ctxColor = "yellow"
            else:
                ctxColor = "green"
            ctxInfo = f" | [{ctxColor}]ctx: {ctxPercent:.0f}%[/{ctxColor}]"

        self.print(f"[dim]Tokens: [/dim][cyan]{totalTokens}[/cyan] [dim]Cost: [/dim][yellow]{costStr}[/yellow]{ctxInfo}")

    async def readInteractiveInput(self) -> str:
        try:
            with patch_stdout():
                input = await self.promptSession.prompt_async(HTML("<b fg='ansiblue'>You:</b> "))
                return input.strip()
        except EOFError as exc:
            raise KeyboardInterrupt from exc
