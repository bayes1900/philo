import asyncio
import httpx
from typing import List
from contextlib import AsyncExitStack
from philo.utils.log import log
from philo.config.pconfig import McpEntry
from philo.agent.toolmanager import ToolManager
from philo.tools.mcp import McpToolWrapper


class McpManager(object):
    def __init__(self, toolManager: ToolManager, mcpEntries: List[McpEntry], logDir=None):
        self.toolManager = toolManager
        self.mcpEntries = mcpEntries
        self.logDir = logDir
        self.connected = False
        self.connecting = False
        self.mcpStack: AsyncExitStack | None = None
        self.cleanupLock = asyncio.Lock()
        self.registeredToolNames: set[str] = set()

    def unregisterTools(self):
        for name in list(self.registeredToolNames):
            self.toolManager.unregister(name)
        self.registeredToolNames.clear()

    async def disconnect(self):
        async with self.cleanupLock:
            self.unregisterTools()
            self.connected = False
            if self.mcpStack is not None:
                try:
                    await self.mcpStack.aclose()
                except RuntimeError as e:
                    # MCP SDK's streamable_http_client uses anyio task groups which bind
                    # cancel scopes to the task that created them. When closing from a
                    # different task context, this error is expected and harmless.
                    if "cancel scope" in str(e):
                        pass  # Silently ignore cancel scope task mismatch
                    else:
                        log.red("Error closing MCP connections: {}".format(e))
                except Exception as e:
                    log.red("Error closing MCP connections: {}".format(e))
                finally:
                    self.mcpStack = None
                    self.connected = False

    async def connect(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.sse import sse_client
        from mcp.client.stdio import stdio_client
        from mcp.client.streamable_http import streamable_http_client

        successCount = 0
        failedCount = 0
        for mcpEntry in self.mcpEntries:
            try:
                transportType = mcpEntry.transportType
                if not transportType:
                    if mcpEntry.command:
                        transportType = "stdio"
                    elif mcpEntry.url:
                        transportType = "sse" if mcpEntry.url.rstrip("/").endswith("/sse") else "streamableHttp"
                    else:
                        log.red("MCP server '{}': no command or url configured, skipping".format(mcpEntry.name))
                        failedCount += 1
                        continue

                if transportType == "stdio":
                    params = StdioServerParameters(
                        command=mcpEntry.command,
                        args=mcpEntry.args,
                        env=mcpEntry.env or None
                    )
                    if self.logDir is not None:
                        self.logDir.mkdir(parents=True, exist_ok=True)
                        errlog = self.mcpStack.enter_context(
                            open(self.logDir / f"mcp-{mcpEntry.name}.log", "a", encoding="utf-8")
                        )
                        read, write = await self.mcpStack.enter_async_context(
                            stdio_client(params, errlog=errlog)
                        )
                    else:
                        read, write = await self.mcpStack.enter_async_context(stdio_client(params))
                elif transportType == "sse":
                    def httpx_client_factory(
                        headers: dict[str, str] | None = None,
                        timeout: httpx.Timeout | None = None,
                        auth: httpx.Auth | None = None,
                    ) -> httpx.AsyncClient:
                        merged_headers = {**(mcpEntry.headers or {}), **(headers or {})}
                        return httpx.AsyncClient(
                            headers=merged_headers or None,
                            follow_redirects=True,
                            timeout=timeout,
                            auth=auth,
                        )
                    read, write = await self.mcpStack.enter_async_context(
                        sse_client(mcpEntry.url, httpx_client_factory=httpx_client_factory)
                    )
                elif transportType == "streamableHttp":
                    http_client = await self.mcpStack.enter_async_context(
                        httpx.AsyncClient(
                            headers=mcpEntry.headers or None,
                            follow_redirects=True,
                            timeout=None,
                        )
                    )
                    read, write, _ = await self.mcpStack.enter_async_context(
                        streamable_http_client(mcpEntry.url, http_client=http_client)
                    )
                else:
                    log.red("MCP server '{}': unknown transport type '{}'".format(mcpEntry.name, transportType))
                    failedCount += 1
                    continue

                session = await self.mcpStack.enter_async_context(ClientSession(read, write))
                await session.initialize()

                tools = await session.list_tools()
                for toolDef in tools.tools:
                    wrapper = McpToolWrapper(session, mcpEntry, toolDef)
                    self.toolManager.register(wrapper)
                    self.registeredToolNames.add(wrapper.name)
                successCount += 1
                log.green("MCP server [{}]: connected, {} tools".format(mcpEntry.name, len(tools.tools)))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                failedCount += 1
                log.red("MCP server [{}]: Failed to connect: {}".format(mcpEntry.name, e))
        return successCount, failedCount

    async def checkConnection(self):
        if len(self.mcpEntries) == 0:
            return
        if self.connecting or self.connected:
            return
        self.connecting = True
        try:
            self.unregisterTools()
            self.mcpStack = AsyncExitStack()
            await self.mcpStack.__aenter__()
            successCount, failedCount = await self.connect()
            self.connected = failedCount == 0 and successCount > 0
            if not self.connected:
                self.unregisterTools()
                if self.mcpStack is not None:
                    try:
                        await self.mcpStack.aclose()
                    except Exception:
                        pass
                    self.mcpStack = None
        except Exception as e:
            log.red("Failed to connect MCP servers (will retry next message): {}".format(e))
            self.unregisterTools()
            if self.mcpStack:
                try:
                    await self.mcpStack.aclose()
                except Exception:
                    pass
                self.mcpStack = None
        finally:
            self.connecting = False
