import os
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from philo.utils.log import log
from philo.utils.misc import safeFilename


TOOL_RESULT_MAX_CHARS = 500


@dataclass
class Session:
    sessionId: str  # channel:chatId
    messages: list[dict[str, Any]] = field(default_factory=list)
    createdAt: datetime = field(default_factory=datetime.now)
    updatedAt: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    nConsolidated: int = 0  # Number of messages already consolidated to files

    def addMessage(self, role: str, content: str, **kwargs: Any):
        msg = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            **kwargs
        }
        self.messages.append(msg)
        self.updatedAt = datetime.now()

    def addMessages(self, messages, numSkips):
        for message in messages[numSkips:]:
            entry = dict(message)
            role, content = entry.get("role"), entry.get("content")
            if role == "assistant" and not content and not entry.get("tool_calls"):
                continue  # skip empty assistant messages — they poison session context
            if role == "tool" and isinstance(content, str) and len(content) > TOOL_RESULT_MAX_CHARS:
                entry["content"] = content[:TOOL_RESULT_MAX_CHARS] + "\n... (truncated)"
            elif role == "user":
                if isinstance(content, list):
                    filtered = []
                    for c in content:
                        if (c.get("type") == "image_url" and c.get("image_url", {}).get("url", "").startswith("data:image/")):
                            filtered.append({"type": "text", "text": "[image]"})
                        else:
                            filtered.append(c)
                    if not filtered:
                        continue
                    entry["content"] = filtered
            entry.setdefault("timestamp", datetime.now().isoformat())
            self.messages.append(entry)
        self.updatedAt = datetime.now()

    def getHistory(self, maxMessages=500) -> list[dict[str, Any]]:
        unconsolidated = self.messages[self.nConsolidated:]
        sliced = unconsolidated[-maxMessages:]
        # Drop leading non-user messages to avoid orphaned tool_result blocks
        for i, m in enumerate(sliced):
            if m.get("role") == "user":
                sliced = sliced[i:]
                break
        out: list[dict[str, Any]] = []
        for m in sliced:
            entry: dict[str, Any] = {"role": m["role"], "content": m.get("content", "")}
            for k in ("tool_calls", "tool_call_id", "name"):
                if k in m:
                    entry[k] = m[k]
            out.append(entry)
        return out

    def clear(self) -> None:
        self.messages = []
        self.nConsolidated = 0
        self.updatedAt = datetime.now()


class SessionManager(object):
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.sessionsDir = self.workspace / "sessions"
        self.sessionsDir.mkdir(parents=True, exist_ok=True)
        self.cache: dict[str, Session] = {}

    def getSessionPath(self, sessionId: str) -> Path:
        return (
            self.sessionsDir / f"{safeFilename(sessionId)}.jsonl",
            self.sessionsDir / f"{safeFilename(sessionId)}.jsonr",
        )

    def getSession(self, sessionId: str, nobuf=False) -> Session:
        if not nobuf and sessionId in self.cache:
            return self.cache[sessionId]
        session = self.loadSession(sessionId, nobuf)
        if session is None:
            session = Session(sessionId=sessionId)
        self.cache[sessionId] = session
        return session

    def loadSession(self, sessionId: str, nobuf=False) -> Session | None:
        path, _ = self.getSessionPath(sessionId)
        if nobuf or not path.exists():
            return None
        try:
            messages = []
            metadata = {}
            createdAt = None
            nConsolidated = 0
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    if data.get("type") == "metadata":
                        metadata = data.get("metadata", {})
                        createdAt = datetime.fromisoformat(data["createdAt"]) if data.get("createdAt") else None
                        nConsolidated = data.get("nConsolidated", 0)
                    else:
                        messages.append(data)
            return Session(
                sessionId=sessionId,
                messages=messages,
                createdAt=createdAt or datetime.now(),
                metadata=metadata,
                nConsolidated=nConsolidated
            )
        except Exception as e:
            log.red("Failed to load session {}: {}", sessionId, e)
            return None

    def dumpSession(self, session: Session):
        path, readablePath = self.getSessionPath(session.sessionId)
        tmpPath = path.with_suffix(".jsonl.tmp")
        tmpReadablePath = readablePath.with_suffix(".jsonr.tmp")
        metadataLine = {
            "type": "metadata",
            "sessionId": session.sessionId,
            "createdAt": session.createdAt.isoformat(),
            "updatedAt": session.updatedAt.isoformat(),
            "metadata": session.metadata,
            "nConsolidated": session.nConsolidated
        }
        try:
            with open(tmpPath, "w", encoding="utf-8") as f, open(tmpReadablePath, "w", encoding="utf-8") as fr:
                f.write(json.dumps(metadataLine, ensure_ascii=False) + "\n")
                fr.write(json.dumps(metadataLine, ensure_ascii=False, indent=2) + "\n")
                for msg in session.messages:
                    f.write(json.dumps(msg, ensure_ascii=False) + "\n")
                    fr.write(json.dumps(msg, ensure_ascii=False, indent=2) + "\n")
            os.replace(tmpPath, path)
            os.replace(tmpReadablePath, readablePath)
        except Exception as e:
            log.red("Failed to dump session {}: {}", session.sessionId, e)
        self.cache[session.sessionId] = session

    def removeSession(self, sessionId: str, deleteFiles: bool = True) -> None:
        self.cache.pop(sessionId, None)
        if not deleteFiles:
            return
        for path in self.getSessionPath(sessionId):
            try:
                os.remove(path)
            except FileNotFoundError:
                pass

    def listSessions(self) -> list[dict[str, Any]]:
        sessions = []
        for path in self.sessionsDir.glob("*.jsonl"):
            try:
                with open(path, encoding="utf-8") as f:
                    firstLine = f.readline().strip()
                    if firstLine:
                        data = json.loads(firstLine)
                        if data.get("type") == "metadata":
                            sessionId = data.get("sessionId") or path.stem.replace("_", ":", 1)
                            sessions.append({
                                "sessionId": sessionId,
                                "createdAt": data.get("createdAt"),
                                "updatedAt": data.get("updatedAt"),
                                "path": str(path)
                            })
            except Exception:
                continue
        return sorted(sessions, key=lambda x: x.get("updatedAt", ""), reverse=True)
