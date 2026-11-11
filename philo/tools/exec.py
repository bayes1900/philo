import os
import re
import asyncio
from pathlib import Path
from typing import Any
from philo.tools.base import ToolBase


class ExecTool(ToolBase):
    def __init__(
        self,
        workspace: str,
        timeout: int = 60,
        restrictToWorkspace: bool = False,
        pathAppends: list[str] = [],
    ):
        self.timeout = timeout
        self.workspace = workspace
        self.denyPatterns = [
            r"\brm\s+-[rf]{1,2}\b",             # rm -r, rm -rf, rm -fr
            r"\bdel\s+/[fq]\b",                 # del /f, del /q
            r"\brmdir\s+/s\b",                  # rmdir /s
            r"(?:^|[;&|]\s*)format\b",          # format (as standalone command only)
            r"\b(mkfs|diskpart)\b",             # disk operations
            r"\bdd\s+if=",                      # dd
            r">\s*/dev/sd",                     # write to disk
            r"\b(shutdown|reboot|poweroff)\b",  # system power
            r":\(\)\s*\{.*\};\s*:",             # fork bomb
            r"\bsudo\b",                        # sudo commands
        ]
        self.allowPatterns = []
        self.restrictToWorkspace = restrictToWorkspace
        self.pathAppends = pathAppends
        self.maxLen = 10000

    @property
    def name(self) -> str:
        return "exec"

    @property
    def description(self) -> str:
        return "Execute a shell command and return its output."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute"
                },
                "working_dir": {
                    "type": "string",
                    "description": "Optional working directory for the command"
                }
            },
            "required": ["command"]
        }

    async def execute(self, command, working_dir=None, **kwargs) -> str:
        cwd = working_dir or self.workspace
        guardError = self.guardCommand(command, cwd)
        if guardError:
            return guardError
        env = os.environ.copy()
        for pathAppend in self.pathAppends:
            env["PATH"] = env.get("PATH", "") + os.pathsep + pathAppend

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout
                )
            except asyncio.TimeoutError:
                try:
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=5.0)
                    except asyncio.TimeoutError:
                        process.kill()
                        try:
                            await asyncio.wait_for(process.wait(), timeout=5.0)
                        except asyncio.TimeoutError:
                            pass
                except Exception:
                    pass
                return f"Error: Command timed out after {self.timeout} seconds"

            outputParts = []
            if stdout:
                outputParts.append(stdout.decode("utf-8", errors="replace"))
            if stderr:
                stderrText = stderr.decode("utf-8", errors="replace")
                if stderrText.strip():
                    outputParts.append(f"STDERR:\n{stderrText}")
            if process.returncode != 0:
                outputParts.append(f"\nExit code: {process.returncode}")

            result = "\n".join(outputParts) if outputParts else "(no output)"
            if len(result) > self.maxLen:
                result = result[:self.maxLen] + f"\n... (truncated, {len(result) - self.maxLen} more chars)"
            return result

        except Exception as e:
            return f"Error executing command: {str(e)}"

    def guardCommand(self, command: str, cwd: str) -> str | None:
        cmd = command.strip()
        lower = cmd.lower()
        for pattern in self.denyPatterns:
            if re.search(pattern, lower):
                return "Error: Command blocked by safety guard (dangerous pattern detected)"
        if self.allowPatterns:
            if not any(re.search(p, lower) for p in self.allowPatterns):
                return "Error: Command blocked by safety guard (not in allowlist)"
        if self.restrictToWorkspace:
            if "../" in cmd:
                return "Error: Command blocked by safety guard (path traversal detected)"
            cwdPath = Path(cwd).resolve()
            for raw in self.extractAbsolutePaths(cmd):
                try:
                    p = Path(raw.strip()).resolve()
                except Exception:
                    continue
                if p.is_absolute() and cwdPath not in p.parents and p != cwdPath:
                    return "Error: Command blocked by safety guard (path outside working dir)"
        return None

    @staticmethod
    def extractAbsolutePaths(command: str) -> list[str]:
        posixPaths = re.findall(r"(?:^|[\s|>])(/[^\s\"'>]+)", command)
        return posixPaths
