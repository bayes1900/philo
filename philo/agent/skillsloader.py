import re
from pathlib import Path


class SkillsLoader(object):
    def __init__(self, pcfg):
        self.pcfg = pcfg
        self.workspaceSkillsDir: Path | None = None
        if pcfg.agentSpace is not None:
            self.workspaceSkillsDir = pcfg.agentSpace / "skills"
        self.builtInSkillsDir = Path(__file__).parent.parent / "resources/skills"
        self.extraSkills: list[dict[str, str]] = []  # In-memory skills: [{"name": "...", "content": "..."}]
        self.extraSkillPaths: list[str] = []  # External skill directory paths

    def addSkill(self, skill) -> None:
        """Add an extra skill. Can be a path string or a dict with 'name' and 'content'."""
        if isinstance(skill, str):
            self.extraSkillPaths.append(skill)
        elif isinstance(skill, dict):
            self.extraSkills.append(skill)

    def listSkills(self) -> list[dict[str, str]]:
        skills = []
        # Extra skills (in-memory)
        for skill in self.extraSkills:
            skills.append({
                "name": skill.get("name", "unnamed"),
                "path": "inline",
                "source": "extra"
            })
        # Extra skill paths
        for skillPath in self.extraSkillPaths:
            p = Path(skillPath)
            if p.is_dir():
                skillFile = p / "SKILL.md"
                if skillFile.exists():
                    skills.append({"name": p.name, "path": str(skillFile), "source": "extra_path"})
            elif p.is_file() and p.name == "SKILL.md":
                skills.append({"name": p.parent.name, "path": str(p), "source": "extra_path"})
        # Workspace skills
        if self.workspaceSkillsDir is not None and self.workspaceSkillsDir.exists():
            for skillDir in self.workspaceSkillsDir.iterdir():
                if skillDir.is_dir():
                    skillFile = skillDir / "SKILL.md"
                    if skillFile.exists() and not any(s["name"] == skillDir.name for s in skills):
                        skills.append({"name": skillDir.name, "path": str(skillFile), "source": "workspace"})
        # Built-in skills
        if self.builtInSkillsDir and self.builtInSkillsDir.exists():
            for skillDir in self.builtInSkillsDir.iterdir():
                if skillDir.is_dir():
                    skillFile = skillDir / "SKILL.md"
                    if skillFile.exists() and not any(s["name"] == skillDir.name for s in skills):
                        skills.append({"name": skillDir.name, "path": str(skillFile), "source": "builtin"})
        return skills

    def loadSkill(self, name: str):
        # Check extra skills (in-memory) first
        for skill in self.extraSkills:
            if skill.get("name") == name:
                return skill.get("content", "")
        # Check extra skill paths
        for skillPath in self.extraSkillPaths:
            p = Path(skillPath)
            if p.is_dir():
                skillFile = p / "SKILL.md"
                if p.name == name and skillFile.exists():
                    return skillFile.read_text(encoding="utf-8")
            elif p.is_file() and p.name == "SKILL.md" and p.parent.name == name:
                return p.read_text(encoding="utf-8")
        # Workspace skills
        if self.workspaceSkillsDir is not None:
            workspaceSkill = self.workspaceSkillsDir / name / "SKILL.md"
            if workspaceSkill.exists():
                return workspaceSkill.read_text(encoding="utf-8")
        # Built-in skills
        if self.builtInSkillsDir:
            builtinSkill = self.builtInSkillsDir / name / "SKILL.md"
            if builtinSkill.exists():
                return builtinSkill.read_text(encoding="utf-8")
        return None

    def loadSkillsForContext(self, skillNames: list[str]) -> str:
        parts = []
        for name in skillNames:
            content = self.loadSkill(name)
            if content:
                content = self.stripFrontmatter(content)
                parts.append(f"### Skill: {name}\n\n{content}")
        return "\n\n---\n\n".join(parts) if parts else ""

    def buildSkillsSummary(self) -> str:
        """
        Build a summary of all skills (name, description, path, availability).
        This is used for progressive loading - the agent can read the full
        skill content using read_file when needed.
        Returns:
            XML-formatted skills summary.
        """
        allSkills = self.listSkills()
        def escapeXml(s: str) -> str:
            return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        lines = ["<skills>"]
        for s in allSkills:
            name = escapeXml(s["name"])
            path = escapeXml(s["path"])
            desc = escapeXml(self.getSkillDescription(s["name"]))
            lines.append("  <skill>")
            lines.append(f"    <name>{name}</name>")
            lines.append(f"    <description>{desc}</description>")
            lines.append(f"    <location>{path}</location>")
            lines.append("  </skill>")
        lines.append("</skills>")
        return "\n".join(lines)

    def buildInlineSkills(self) -> str:
        parts = []
        for skill in self.extraSkills:
            name = skill.get("name", "unnamed")
            content = self.stripFrontmatter(skill.get("content") or "")
            if content:
                parts.append(f"### Skill: {name}\n\n{content}")
        return "\n\n---\n\n".join(parts)

    def getSkillDescription(self, name: str) -> str:
        meta = self.getSkillFrontMatter(name)
        if meta and meta.get("description"):
            return meta["description"]
        return name  # Fallback to skill name

    def stripFrontmatter(self, content: str) -> str:
        if content.startswith("---"):
            match = re.match(r"^---\r?\n.*?\r?\n---\r?\n", content, re.DOTALL)
            if match:
                return content[match.end():].strip()
        return content

    def getSkillMeta(self, name: str) -> dict:
        meta = self.getSkillFrontMatter(name) or {}
        return meta.get("metadata", "")

    def getSkillFrontMatter(self, name: str):
        content = self.loadSkill(name)
        if not content:
            return None
        if content.startswith("---"):
            match = re.match(r"^---\r?\n(.*?)\r?\n---", content, re.DOTALL)
            if match:
                try:
                    import yaml
                    metadata = yaml.safe_load(match.group(1))
                    return metadata if isinstance(metadata, dict) else {}
                except ImportError:
                    # Fallback to simple parsing if yaml not available
                    metadata = {}
                    for line in match.group(1).split("\n"):
                        if ":" in line:
                            key, value = line.split(":", 1)
                            metadata[key.strip()] = value.strip().strip('"\'')
                    return metadata
        return None
