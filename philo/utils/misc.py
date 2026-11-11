import os
import re
import html
import atexit
import tempfile
import shutil
from urllib.parse import urlparse
from pathlib import Path


def createShmDir(prefix):
    shmRoot = "/dev/shm"
    tmpdir = None
    if os.path.isdir(shmRoot) and os.access(shmRoot, os.W_OK):
        try:
            userDir = os.getenv("USER") or "philo"
            dirpath = os.path.join(shmRoot, userDir, prefix)
            os.makedirs(dirpath, mode=0o700, exist_ok=True)
            tmpdir = tempfile.mkdtemp(dir=dirpath)
        except OSError:
            tmpdir = None
    if tmpdir is None:
        tmpdir = tempfile.mkdtemp(prefix="{}_".format(prefix))
    atexit.register(lambda: shutil.rmtree(tmpdir, ignore_errors=True))
    return tmpdir


def detectImageMime(data: bytes) -> str | None:
    """Detect image MIME type from magic bytes, ignoring file extension."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def stripTags(text: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re.sub(r'<script[\s\S]*?</script>', '', text, flags=re.I)
    text = re.sub(r'<style[\s\S]*?</style>', '', text, flags=re.I)
    text = re.sub(r'<[^>]+>', '', text)
    return html.unescape(text).strip()


def normalize(text: str) -> str:
    """Normalize whitespace."""
    text = re.sub(r'[ \t]+', ' ', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def validateUrl(url: str) -> tuple[bool, str]:
    """Validate URL: must be http(s) with valid domain."""
    try:
        p = urlparse(url)
        if p.scheme not in ('http', 'https'):
            return False, f"Only http/https allowed, got '{p.scheme or 'none'}'"
        if not p.netloc:
            return False, "Missing domain"
        return True, ""
    except Exception as e:
        return False, str(e)


UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*]')

def safeFilename(name: str) -> str:
    """Replace unsafe path characters with underscores."""
    return UNSAFE_CHARS.sub("_", name).strip()


def resolvePath(path: str, workspace: Path | None = None, allowedDir: Path | None = None) -> Path:
    """Resolve path against workspace (if relative) and enforce directory restriction."""
    p = Path(path).expanduser()
    if not p.is_absolute() and workspace:
        p = workspace / p
    resolved = p.resolve()
    if allowedDir:
        try:
            resolved.relative_to(allowedDir.resolve())
        except ValueError:
            raise PermissionError(f"Path {path} is outside allowed directory {allowedDir}")
    return resolved


def getSkillMd(name):
    localPath = Path(__file__).resolve()
    currentDir = localPath.parent.parent
    path = currentDir / "resources" / "skills" / name
    if not path.exists():
        raise ValueError("Skill not found: {}".format(name))
    return str(path)


def getYaml(name):
    localPath = Path(__file__).resolve()
    currentDir = localPath.parent.parent
    path = currentDir / "resources" / "yamls" / name
    if not path.exists():
        raise ValueError("Yaml not found: {}".format(name))
    return str(path)


def removeFiles(files):
    if not isinstance(files, list) and not isinstance(files, tuple):
        files = [files]
    for file in files:
        try:
            os.remove(file)
        except:
            pass
