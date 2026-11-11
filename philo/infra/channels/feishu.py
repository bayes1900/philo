import os
import re
import json
import time
import asyncio
import threading
from pathlib import Path
from typing import Any
from philo.utils.log import log
from philo.infra.bus import OutboundMessage
from philo.infra.bus import MessageBus
from philo.infra.channels.base import BaseChannel


class MessageContentBuilder:
    tableRe = re.compile(
        r"((?:^[ \t]*\|.+\|[ \t]*\n)(?:^[ \t]*\|[-:\s|]+\|[ \t]*\n)(?:^[ \t]*\|.+\|[ \t]*\n?)+)",
        re.MULTILINE,
    )
    headingRe = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
    codeBlockRe = re.compile(r"(```[\s\S]*?```)", re.MULTILINE)
    complexMdRe = re.compile(
        r"```"                          # fenced code block
        r"|^\|.+\|.*\n\s*\|[-:\s|]+\|"  # markdown table (header + separator)
        r"|^#{1,6}\s+"                  # headings
        , re.MULTILINE,
    )
    simpleMdRe = re.compile(
        r"\*\*.+?\*\*"                           # **bold**
        r"|__.+?__"                              # __bold__
        r"|(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)"  # *italic* (single *)
        r"|~~.+?~~"                              # ~~strikethrough~~
        , re.DOTALL,
    )
    mdLinkRe = re.compile(r"\[([^\]]+)\]\((https?://[^\)]+)\)")
    listRe = re.compile(r"^[\s]*[-*+]\s+", re.MULTILINE)
    olistRe = re.compile(r"^[\s]*\d+\.\s+", re.MULTILINE)
    textMaxLen = 200
    postMaxLen = 2000

    @staticmethod
    def parseMdTable(tableText: str) -> dict | None:
        """Parse a markdown table into a Feishu table element."""
        lines = [line.strip() for line in tableText.strip().split("\n") if line.strip()]
        if len(lines) < 3:
            return None
        def split(line: str) -> list[str]:
            return [c.strip() for c in line.strip("|").split("|")]
        headers = split(lines[0])
        rows = [split(line) for line in lines[2:]]
        columns = [{"tag": "column", "name": f"c{i}", "display_name": h, "width": "auto"}
                   for i, h in enumerate(headers)]
        return {
            "tag": "table",
            "page_size": len(rows) + 1,
            "columns": columns,
            "rows": [{f"c{i}": r[i] if i < len(r) else "" for i in range(len(headers))} for r in rows],
        }

    @staticmethod
    def splitElementsByTableLimit(elements: list[dict], maxTables: int = 1) -> list[list[dict]]:
        """Split card elements into groups with at most *maxTables* table elements each.
        Feishu cards have a hard limit of one table per card (API error 11310).
        When the rendered content contains multiple markdown tables each table is
        placed in a separate card message so every table reaches the user.
        """
        if not elements:
            return [[]]
        groups: list[list[dict]] = []
        current: list[dict] = []
        tableCount = 0
        for el in elements:
            if el.get("tag") == "table":
                if tableCount >= maxTables:
                    if current:
                        groups.append(current)
                    current = []
                    tableCount = 0
                current.append(el)
                tableCount += 1
            else:
                current.append(el)
        if current:
            groups.append(current)
        return groups or [[]]

    @classmethod
    def detectFormat(cls, content: str) -> str:
        """Determine the optimal Feishu message format for *content*.
        Returns one of:
        - ``"text"``        – plain text, short and no markdown
        - ``"post"``        – rich text (links only, moderate length)
        - ``"interactive"`` – card with full markdown rendering
        """
        stripped = content.strip()
        if cls.complexMdRe.search(stripped):
            return "interactive"
        if len(stripped) > cls.postMaxLen:
            return "interactive"
        if cls.simpleMdRe.search(stripped):
            return "interactive"
        if cls.listRe.search(stripped) or cls.olistRe.search(stripped):
            return "interactive"
        if cls.mdLinkRe.search(stripped):
            return "post"
        if len(stripped) <= cls.textMaxLen:
            return "text"
        return "post"

    @classmethod
    def markdownToPost(cls, content: str) -> str:
        """Convert markdown content to Feishu post message JSON.

        Handles links ``[text](url)`` as ``a`` tags; everything else as ``text`` tags.
        Each line becomes a paragraph (row) in the post body.
        """
        lines = content.strip().split("\n")
        paragraphs: list[list[dict]] = []

        for line in lines:
            elements: list[dict] = []
            lastEnd = 0

            for m in cls.mdLinkRe.finditer(line):
                # Text before this link
                before = line[lastEnd:m.start()]
                if before:
                    elements.append({"tag": "text", "text": before})
                elements.append({
                    "tag": "a",
                    "text": m.group(1),
                    "href": m.group(2),
                })
                lastEnd = m.end()

            # Remaining text after last link
            remaining = line[lastEnd:]
            if remaining:
                elements.append({"tag": "text", "text": remaining})

            # Empty line → empty paragraph for spacing
            if not elements:
                elements.append({"tag": "text", "text": ""})

            paragraphs.append(elements)

        postBody = {
            "zh_cn": {
                "content": paragraphs,
            }
        }
        return json.dumps(postBody, ensure_ascii=False)

    def buildCardElements(self, content: str) -> list[dict]:
        """Split content into div/markdown + table elements for Feishu card."""
        elements, lastEnd = [], 0
        for m in self.tableRe.finditer(content):
            before = content[lastEnd:m.start()]
            if before.strip():
                elements.extend(self.splitHeadings(before))
            elements.append(self.parseMdTable(m.group(1)) or {"tag": "markdown", "content": m.group(1)})
            lastEnd = m.end()
        remaining = content[lastEnd:]
        if remaining.strip():
            elements.extend(self.splitHeadings(remaining))
        return elements or [{"tag": "markdown", "content": content}]

    def splitHeadings(self, content: str) -> list[dict]:
        """Split content by headings, converting headings to div elements."""
        protected = content
        codeBlocks = []
        for m in self.codeBlockRe.finditer(content):
            codeBlocks.append(m.group(1))
            protected = protected.replace(m.group(1), f"\x00CODE{len(codeBlocks)-1}\x00", 1)

        elements = []
        lastEnd = 0
        for m in self.headingRe.finditer(protected):
            before = protected[lastEnd:m.start()].strip()
            if before:
                elements.append({"tag": "markdown", "content": before})
            text = m.group(2).strip()
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**{text}**",
                },
            })
            lastEnd = m.end()
        remaining = protected[lastEnd:].strip()
        if remaining:
            elements.append({"tag": "markdown", "content": remaining})

        for i, cb in enumerate(codeBlocks):
            for el in elements:
                if el.get("tag") == "markdown":
                    el["content"] = el["content"].replace(f"\x00CODE{i}\x00", cb)

        return elements or [{"tag": "markdown", "content": content}]

    @staticmethod
    def extractShareCardContent(contentJson: dict, msgType: str) -> str:
        """Extract text representation from share cards and interactive messages."""
        parts = []

        if msgType == "share_chat":
            parts.append(f"[shared chat: {contentJson.get('chat_id', '')}]")
        elif msgType == "share_user":
            parts.append(f"[shared user: {contentJson.get('user_id', '')}]")
        elif msgType == "interactive":
            parts.extend(MessageContentBuilder.extractInteractiveContent(contentJson))
        elif msgType == "share_calendar_event":
            parts.append(f"[shared calendar event: {contentJson.get('event_key', '')}]")
        elif msgType == "system":
            parts.append("[system message]")
        elif msgType == "merge_forward":
            parts.append("[merged forward messages]")

        return "\n".join(parts) if parts else f"[{msgType}]"

    @staticmethod
    def extractInteractiveContent(content: dict) -> list[str]:
        """Recursively extract text and links from interactive card content."""
        parts = []

        if isinstance(content, str):
            try:
                content = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                return [content] if content.strip() else []

        if not isinstance(content, dict):
            return parts

        if "title" in content:
            title = content["title"]
            if isinstance(title, dict):
                titleContent = title.get("content", "") or title.get("text", "")
                if titleContent:
                    parts.append(f"title: {titleContent}")
            elif isinstance(title, str):
                parts.append(f"title: {title}")

        for elements in content.get("elements", []) if isinstance(content.get("elements"), list) else []:
            for element in elements:
                parts.extend(MessageContentBuilder.extractElementContent(element))

        card = content.get("card", {})
        if card:
            parts.extend(MessageContentBuilder.extractInteractiveContent(card))

        header = content.get("header", {})
        if header:
            headerTitle = header.get("title", {})
            if isinstance(headerTitle, dict):
                headerText = headerTitle.get("content", "") or headerTitle.get("text", "")
                if headerText:
                    parts.append(f"title: {headerText}")

        return parts

    @staticmethod
    def extractElementContent(element: dict) -> list[str]:
        """Extract content from a single card element."""
        parts = []

        if not isinstance(element, dict):
            return parts

        tag = element.get("tag", "")

        if tag in ("markdown", "lark_md"):
            content = element.get("content", "")
            if content:
                parts.append(content)

        elif tag == "div":
            text = element.get("text", {})
            if isinstance(text, dict):
                textContent = text.get("content", "") or text.get("text", "")
                if textContent:
                    parts.append(textContent)
            elif isinstance(text, str):
                parts.append(text)
            for field in element.get("fields", []):
                if isinstance(field, dict):
                    fieldText = field.get("text", {})
                    if isinstance(fieldText, dict):
                        c = fieldText.get("content", "")
                        if c:
                            parts.append(c)

        elif tag == "a":
            href = element.get("href", "")
            text = element.get("text", "")
            if href:
                parts.append(f"link: {href}")
            if text:
                parts.append(text)

        elif tag == "button":
            text = element.get("text", {})
            if isinstance(text, dict):
                c = text.get("content", "")
                if c:
                    parts.append(c)
            url = element.get("url", "") or element.get("multi_url", {}).get("url", "")
            if url:
                parts.append(f"link: {url}")

        elif tag == "img":
            alt = element.get("alt", {})
            parts.append(alt.get("content", "[image]") if isinstance(alt, dict) else "[image]")

        elif tag == "note":
            for ne in element.get("elements", []):
                parts.extend(MessageContentBuilder.extractElementContent(ne))

        elif tag == "column_set":
            for col in element.get("columns", []):
                for ce in col.get("elements", []):
                    parts.extend(MessageContentBuilder.extractElementContent(ce))

        elif tag == "plain_text":
            content = element.get("content", "")
            if content:
                parts.append(content)

        else:
            for ne in element.get("elements", []):
                parts.extend(MessageContentBuilder.extractElementContent(ne))

        return parts

    @staticmethod
    def extractPostContent(contentJson: dict) -> tuple[str, list[str]]:
        """Extract text and image keys from Feishu post (rich text) message.

        Handles three payload shapes:
        - Direct:    {"title": "...", "content": [[...]]}
        - Localized: {"zh_cn": {"title": "...", "content": [...]}}
        - Wrapped:   {"post": {"zh_cn": {"title": "...", "content": [...]}}}
        """

        def parseBlock(block: dict) -> tuple[str | None, list[str]]:
            if not isinstance(block, dict) or not isinstance(block.get("content"), list):
                return None, []
            texts, images = [], []
            if title := block.get("title"):
                texts.append(title)
            for row in block["content"]:
                if not isinstance(row, list):
                    continue
                for el in row:
                    if not isinstance(el, dict):
                        continue
                    tag = el.get("tag")
                    if tag in ("text", "a"):
                        texts.append(el.get("text", ""))
                    elif tag == "at":
                        texts.append(f"@{el.get('user_name', 'user')}")
                    elif tag == "img" and (key := el.get("image_key")):
                        images.append(key)
            return (" ".join(texts).strip() or None), images

        # Unwrap optional {"post": ...} envelope
        root = contentJson
        if isinstance(root, dict) and isinstance(root.get("post"), dict):
            root = root["post"]
        if not isinstance(root, dict):
            return "", []

        # Direct format
        if "content" in root:
            text, imgs = parseBlock(root)
            if text or imgs:
                return text or "", imgs

        # Localized: prefer known locales, then fall back to any dict child
        for key in ("zh_cn", "en_us", "ja_jp"):
            if key in root:
                text, imgs = parseBlock(root[key])
                if text or imgs:
                    return text or "", imgs
        for val in root.values():
            if isinstance(val, dict):
                text, imgs = parseBlock(val)
                if text or imgs:
                    return text or "", imgs

        return "", []


class FeishuChannel(BaseChannel):
    imageExts = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico", ".tiff", ".tif"}
    fileTypeMap = {
        ".pdf": "pdf", ".doc": "doc", ".docx": "doc",
        ".xls": "xls", ".xlsx": "xls", ".ppt": "ppt", ".pptx": "ppt",
    }

    def __init__(self, root: Path, appId: str, appSecret: str, bus: MessageBus, allowedIds=None):
        super().__init__("feishu", bus, allowedIds)
        self.root = root
        self.fileDir = root / "media"
        self.fileDir.mkdir(parents=True, exist_ok=True)
        self.appId = appId
        self.appSecret = appSecret
        self.client = None
        self.wsClient = None
        self.wsThread = None
        self.processedMessageIds: dict[str, float] = {}
        self.loop: asyncio.AbstractEventLoop | None = None
        self.running = False
        self.contentBuilder = MessageContentBuilder()

    def websocketClientLoop(self):
        import lark_oapi.ws.client as larkWsClient
        wsLoop = asyncio.new_event_loop()
        asyncio.set_event_loop(wsLoop)
        larkWsClient.loop = wsLoop
        try:
            while self.running:
                try:
                    self.wsClient.start()
                except Exception as e:
                    log.yellow("Feishu WebSocket error: {}", e)
                if self.running:
                    time.sleep(5)
        finally:
            wsLoop.close()

    async def start(self):
        import lark_oapi as lark
        self.loop = asyncio.get_running_loop()
        self.client = (
            lark.Client.builder()
            .app_id(self.appId)
            .app_secret(self.appSecret)
            .log_level(lark.LogLevel.INFO)
            .build()
        )
        builder = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self.onMsg)
            .register_p2_im_message_reaction_created_v1(self.onReaction)
            .register_p2_im_message_message_read_v1(self.onMsgRead)
            .register_p2_im_chat_access_event_bot_p2p_chat_entered_v1(self.onP2pChatEntered)
        )
        eventHandler = builder.build()
        self.wsClient = lark.ws.Client(
            self.appId,
            self.appSecret,
            event_handler=eventHandler,
            log_level=lark.LogLevel.INFO
        )

        # Start WebSocket client in a separate thread with reconnect loop.
        # A dedicated event loop is created for this thread so that lark_oapi's
        # module-level `loop = asyncio.get_event_loop()` picks up an idle loop
        # instead of the already-running main asyncio loop, which would cause
        # "This event loop is already running" errors.
        self.running = True
        self.wsThread = threading.Thread(target=self.websocketClientLoop, daemon=True)
        self.wsThread.start()
        log.inf("Feishu bot started")

        while self.running:
            await asyncio.sleep(1)

    async def stop(self):
        self.running = False
        if self.wsThread and self.wsThread.is_alive():
            self.wsThread.join(timeout=5)
        log.inf("Feishu bot exited")

    def cleanProcessedMessageIds(self, maxAge=3600):
        now = time.time()
        expired = [mid for mid, ts in self.processedMessageIds.items() if now - ts > maxAge]
        for mid in expired:
            del self.processedMessageIds[mid]

    def addReactionSync(self, messageId: str, emojiType: str) -> None:
        from lark_oapi.api.im.v1 import CreateMessageReactionRequest, CreateMessageReactionRequestBody, Emoji
        try:
            request = CreateMessageReactionRequest.builder() \
                .message_id(messageId) \
                .request_body(
                    CreateMessageReactionRequestBody.builder()
                    .reaction_type(Emoji.builder().emoji_type(emojiType).build())
                    .build()
                ).build()
            response = self.client.im.v1.message_reaction.create(request)
            if not response.success():
                log.red("Failed to add reaction: code={}, msg={}", response.code, response.msg)
        except Exception as e:
            log.red("Error adding reaction: {}", e)

    async def addReaction(self, messageId: str, emojiType: str = "THUMBSUP") -> None:
        if not self.client:
            return
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.addReactionSync, messageId, emojiType)

    def uploadImageSync(self, filePath: str) -> str | None:
        from lark_oapi.api.im.v1 import CreateImageRequest, CreateImageRequestBody
        try:
            with open(filePath, "rb") as f:
                request = CreateImageRequest.builder() \
                    .request_body(
                        CreateImageRequestBody.builder()
                        .image_type("message")
                        .image(f)
                        .build()
                    ).build()
                response = self.client.im.v1.image.create(request)
                if response.success():
                    imageKey = response.data.image_key
                    return imageKey
                else:
                    log.red("Failed to upload image: code={}, msg={}", response.code, response.msg)
                    return None
        except Exception as e:
            log.red("Error uploading image {}: {}", filePath, e)
            return None

    def uploadFileSync(self, filePath: str) -> str | None:
        """Upload a file to Feishu and return the file_key."""
        from lark_oapi.api.im.v1 import CreateFileRequest, CreateFileRequestBody
        ext = os.path.splitext(filePath)[1].lower()
        fileType = self.fileTypeMap.get(ext, "stream")
        fileName = os.path.basename(filePath)
        try:
            with open(filePath, "rb") as f:
                request = (
                    CreateFileRequest.builder()
                    .request_body(
                        CreateFileRequestBody.builder()
                        .file_type(fileType)
                        .file_name(fileName)
                        .file(f)
                        .build()
                    ).build()
                )
                response = self.client.im.v1.file.create(request)
                if response.success():
                    fileKey = response.data.file_key
                    return fileKey
                else:
                    log.red("Failed to upload file: code={}, msg={}", response.code, response.msg)
                    return None
        except Exception as e:
            log.red("Error uploading file {}: {}", filePath, e)
            return None

    def downloadImageSync(self, messageId: str, imageKey: str):
        """Download an image from Feishu message by message_id and image_key."""
        from lark_oapi.api.im.v1 import GetMessageResourceRequest
        try:
            request = (
                GetMessageResourceRequest.builder()
                .message_id(messageId)
                .file_key(imageKey)
                .type("image")
                .build()
            )
            response = self.client.im.v1.message_resource.get(request)
            if response.success():
                fileData = response.file
                # GetMessageResourceRequest returns BytesIO, need to read bytes
                if hasattr(fileData, "read"):
                    fileData = fileData.read()
                return fileData, response.file_name
            else:
                log.red("Failed to download image: code={}, msg={}", response.code, response.msg)
                return None, None
        except Exception as e:
            log.red("Error downloading image {}: {}", imageKey, e)
            return None, None

    def downloadFileSync(self, messageId: str, fileKey: str, resourceType: str = "file"):
        """Download a file/media from a Feishu message by message_id and file_key."""
        from lark_oapi.api.im.v1 import GetMessageResourceRequest
        try:
            request = (
                GetMessageResourceRequest.builder()
                .message_id(messageId)
                .file_key(fileKey)
                .type(resourceType)
                .build()
            )
            response = self.client.im.v1.message_resource.get(request)
            if response.success():
                fileData = response.file
                if hasattr(fileData, "read"):
                    fileData = fileData.read()
                return fileData, response.file_name
            else:
                log.red("Failed to download {}: code={}, msg={}", resourceType, response.code, response.msg)
                return None, None
        except Exception:
            log.red("Error downloading {} {}", resourceType, fileKey)
            return None, None

    async def downloadAndSaveFile(
        self,
        msgType: str,
        contentJson: dict,
        messageId: str | None = None
    ) -> tuple[str | None, str]:
        """
        Download media from Feishu and save to local disk.

        Returns:
            (filePath, contentText) - filePath is None if download failed
        """
        loop = asyncio.get_running_loop()
        data, filename = None, None

        if msgType == "image":
            imageKey = contentJson.get("image_key")
            if imageKey and messageId:
                data, filename = await loop.run_in_executor(
                    None, self.downloadImageSync, messageId, imageKey
                )
                if not filename:
                    filename = f"{imageKey[:16]}.jpg"

        elif msgType == "file":
            fileKey = contentJson.get("file_key")
            if fileKey and messageId:
                data, filename = await loop.run_in_executor(
                    None, self.downloadFileSync, messageId, fileKey, msgType
                )
                if not filename:
                    filename = f"{fileKey[:16]}"

        if data and filename:
            filePath = self.fileDir / filename
            filePath.write_bytes(data)
            return str(filePath), f"[{msgType}: {filename}]"

        return None, f"[{msgType}: download failed]"

    def sendMessageSync(self, receiveIdType: str, receiveId: str, msgType: str, content: str) -> bool:
        """Send a single message (text/image/file/interactive) synchronously."""
        from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody
        try:
            request = CreateMessageRequest.builder() \
                .receive_id_type(receiveIdType) \
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(receiveId)
                    .msg_type(msgType)
                    .content(content)
                    .build()
                ).build()
            response = self.client.im.v1.message.create(request)
            if not response.success():
                log.red(
                    "Failed to send Feishu {} message: code={}, msg={}, log_id={}",
                    msgType, response.code, response.msg, response.get_log_id()
                )
                return False
            return True
        except Exception as e:
            log.red("Error sending Feishu {} message: {}", msgType, e)
            return False

    async def send(self, msg: OutboundMessage) -> None:
        try:
            receiveIdType = "chat_id" if msg.chatId.startswith("oc_") else "open_id"
            loop = asyncio.get_running_loop()

            for filePath in msg.media:
                if not os.path.isfile(filePath):
                    log.yellow("Media file not found: {}", filePath)
                    continue
                ext = os.path.splitext(filePath)[1].lower()
                if ext in self.imageExts:
                    key = await loop.run_in_executor(None, self.uploadImageSync, filePath)
                    if key:
                        await loop.run_in_executor(
                            None, self.sendMessageSync,
                            receiveIdType, msg.chatId, "image", json.dumps({"image_key": key}, ensure_ascii=False),
                        )
                else:
                    key = await loop.run_in_executor(None, self.uploadFileSync, filePath)
                    if key:
                        await loop.run_in_executor(
                            None, self.sendMessageSync,
                            receiveIdType, msg.chatId, "file", json.dumps({"file_key": key}, ensure_ascii=False),
                        )

            if msg.content and msg.content.strip():
                fmt = MessageContentBuilder.detectFormat(msg.content)

                if fmt == "text":
                    # Short plain text – send as simple text message
                    textBody = json.dumps({"text": msg.content.strip()}, ensure_ascii=False)
                    await loop.run_in_executor(
                        None, self.sendMessageSync,
                        receiveIdType, msg.chatId, "text", textBody,
                    )

                elif fmt == "post":
                    # Medium content with links – send as rich-text post
                    postBody = MessageContentBuilder.markdownToPost(msg.content)
                    await loop.run_in_executor(
                        None, self.sendMessageSync,
                        receiveIdType, msg.chatId, "post", postBody,
                    )

                else:
                    # Complex / long content – send as interactive card
                    elements = self.contentBuilder.buildCardElements(msg.content)
                    for chunk in MessageContentBuilder.splitElementsByTableLimit(elements):
                        card = {"config": {"wide_screen_mode": True}, "elements": chunk}
                        await loop.run_in_executor(
                            None, self.sendMessageSync,
                            receiveIdType, msg.chatId, "interactive", json.dumps(card, ensure_ascii=False),
                        )

        except Exception as e:
            log.red("Error sending Feishu message: {}", e)

    def onMsg(self, data: Any) -> None:
        """
        Sync handler for incoming messages (called from WebSocket thread).
        Schedules async handling in the main event loop.
        """
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.onMessage(data), self.loop)

    async def onMessage(self, data: Any) -> None:
        try:
            event = data.event
            message = event.message
            sender = event.sender

            if sender.sender_type == "bot":
                return
            messageId = message.message_id
            if messageId in self.processedMessageIds:
                return
            self.processedMessageIds[messageId] = time.time()
            self.cleanProcessedMessageIds()

            await self.addReaction(messageId)

            senderId = sender.sender_id.open_id if sender.sender_id else "unknown"
            chatId = message.chat_id
            chatType = message.chat_type
            msgType = message.message_type
            contentParts = []
            files = []

            try:
                contentJson = json.loads(message.content) if message.content else {}
            except json.JSONDecodeError:
                contentJson = {}

            if msgType == "text":
                text = contentJson.get("text", "")
                if text:
                    contentParts.append(text)

            elif msgType == "post":
                text, imageKeys = MessageContentBuilder.extractPostContent(contentJson)
                if text:
                    contentParts.append(text)
                for imgKey in imageKeys:
                    filePath, contentText = await self.downloadAndSaveFile(
                        "image", {"image_key": imgKey}, messageId
                    )
                    if filePath:
                        files.append(filePath)
                    contentParts.append(contentText)

            elif msgType in ("image", "file"):
                filePath, contentText = await self.downloadAndSaveFile(msgType, contentJson, messageId)
                if filePath:
                    files.append(filePath)
                contentParts.append(contentText)
            elif msgType in ("share_chat", "share_user", "interactive", "share_calendar_event", "system", "merge_forward"):
                text = MessageContentBuilder.extractShareCardContent(contentJson, msgType)
                if text:
                    contentParts.append(text)
            else:
                MSG_TYPE_MAP = {
                    "image": "[image]",
                    "file": "[file]",
                    "sticker": "[sticker]",
                }
                contentParts.append(MSG_TYPE_MAP.get(msgType, f"[{msgType}]"))

            content = "\n".join(contentParts) if contentParts else ""
            if not content and not files:
                return

            # Forward to message bus
            replyTo = chatId if chatType == "group" else senderId
            await self.handleMessage(
                senderId=senderId,
                chatId=replyTo,
                content=content,
                files=files,
                metadata={
                    "message_id": messageId,
                    "messageId": messageId,
                    "chatType": chatType,
                    "msgType": msgType,
                }
            )
        except Exception as e:
            log.red("Error processing Feishu message: {}", e)

    def onReaction(self, data: Any) -> None:
        pass

    def onMsgRead(self, data: Any) -> None:
        pass

    def onP2pChatEntered(self, data: Any) -> None:
        pass
