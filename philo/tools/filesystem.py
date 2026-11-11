import difflib
from pathlib import Path
from typing import Any
from philo.tools.base import ToolBase
from philo.utils.misc import resolvePath


class ReadFileTool(ToolBase):
    def __init__(self, workspace: Path | None = None, allowedDir: Path | None = None):
        self.workspace = workspace
        self.allowedDir = allowedDir
        self.maxChars = 128000

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "Read the contents of a file at the given path."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "The file path to read"}},
            "required": ["path"],
        }

    async def execute(self, path, **kwargs) -> str:
        try:
            filePath = resolvePath(path, self.workspace, self.allowedDir)
            if not filePath.exists():
                return f"Error: File not found: {path}"
            if not filePath.is_file():
                return f"Error: Not a file: {path}"
            size = filePath.stat().st_size
            if size > self.maxChars * 4:  # rough upper bound (UTF-8 chars ≤ 4 bytes)
                return (
                    f"Error: File too large ({size:,} bytes). "
                    f"Use exec tool with head/tail/grep to read portions."
                )
            content = filePath.read_text(encoding="utf-8")
            if len(content) > self.maxChars:
                return content[: self.maxChars] + f"\n\n... (truncated — file is {len(content):,} chars, limit {self.maxChars:,})"
            return content
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error reading file: {str(e)}"


class WriteFileTool(ToolBase):
    def __init__(self, workspace: Path | None = None, allowedDir: Path | None = None):
        self.workspace = workspace
        self.allowedDir = allowedDir

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "Write content to a file at the given path. Creates parent directories if needed."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The file path to write to"},
                "content": {"type": "string", "description": "The content to write"},
            },
            "required": ["path", "content"],
        }

    async def execute(self, path, content, **kwargs) -> str:
        try:
            filePath = resolvePath(path, self.workspace, self.allowedDir)
            filePath.parent.mkdir(parents=True, exist_ok=True)
            filePath.write_text(content, encoding="utf-8")
            return f"Successfully wrote {len(content)} bytes to {filePath}"
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error writing file: {str(e)}"


class EditFileTool(ToolBase):
    def __init__(self, workspace: Path | None = None, allowedDir: Path | None = None):
        self.workspace = workspace
        self.allowedDir = allowedDir

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return "Edit a file by replacing old_text with new_text. The old_text must exist exactly in the file."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The file path to edit"},
                "old_text": {"type": "string", "description": "The exact text to find and replace"},
                "new_text": {"type": "string", "description": "The text to replace with"},
            },
            "required": ["path", "old_text", "new_text"],
        }

    async def execute(self, path: str, old_text: str, new_text: str, **kwargs: Any) -> str:
        try:
            filePath = resolvePath(path, self.workspace, self.allowedDir)
            if not filePath.exists():
                return f"Error: File not found: {path}"
            content = filePath.read_text(encoding="utf-8")
            if old_text not in content:
                return self.notFoundMessage(old_text, content, path)
            # Count occurrences
            count = content.count(old_text)
            if count > 1:
                return f"Warning: old_text appears {count} times. Please provide more context to make it unique."
            newContent = content.replace(old_text, new_text, 1)
            filePath.write_text(newContent, encoding="utf-8")
            return f"Successfully edited {filePath}"
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error editing file: {str(e)}"

    @staticmethod
    def notFoundMessage(old_text: str, content: str, path: str) -> str:
        """Build a helpful error when old_text is not found."""
        lines = content.splitlines(keepends=True)
        oldLines = old_text.splitlines(keepends=True)
        window = len(oldLines)

        bestRatio, bestStart = 0.0, 0
        for i in range(max(1, len(lines) - window + 1)):
            ratio = difflib.SequenceMatcher(None, oldLines, lines[i : i + window]).ratio()
            if ratio > bestRatio:
                bestRatio, bestStart = ratio, i

        if bestRatio > 0.5:
            diff = "\n".join(
                difflib.unified_diff(
                    oldLines,
                    lines[bestStart : bestStart + window],
                    fromfile="old_text (provided)",
                    tofile=f"{path} (actual, line {bestStart + 1})",
                    lineterm="",
                )
            )
            return f"Error: old_text not found in {path}.\nBest match ({bestRatio:.0%} similar) at line {bestStart + 1}:\n{diff}"
        return (
            f"Error: old_text not found in {path}. No similar text found. Verify the file content."
        )


class ListDirTool(ToolBase):
    def __init__(self, workspace: Path | None = None, allowedDir: Path | None = None):
        self.workspace = workspace
        self.allowedDir = allowedDir

    @property
    def name(self) -> str:
        return "list_dir"

    @property
    def description(self) -> str:
        return "List the contents of a directory."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "The directory path to list"}},
            "required": ["path"],
        }

    async def execute(self, path: str, **kwargs: Any) -> str:
        try:
            dirPath = resolvePath(path, self.workspace, self.allowedDir)
            if not dirPath.exists():
                return f"Error: Directory not found: {path}"
            if not dirPath.is_dir():
                return f"Error: Not a directory: {path}"
            items = []
            for item in sorted(dirPath.iterdir()):
                prefix = "📁 " if item.is_dir() else "📄 "
                items.append(f"{prefix}{item.name}")
            if not items:
                return f"Directory {path} is empty"
            return "\n".join(items)
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error listing directory: {str(e)}"
