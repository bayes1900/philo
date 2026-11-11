import os
import yaml
from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString
from ruamel.yaml.comments import CommentedMap, CommentedSeq


class YamlLoader(dict):
    def __init__(self, filename) -> None:
        super().__init__()
        with open(filename, "r", encoding="utf8") as f:
            prompt_yaml_dict = yaml.safe_load(f)
        if prompt_yaml_dict is None:
            raise ValueError("Failed to load yaml: {}".format(filename))
        for key, value in prompt_yaml_dict.items():
            self[key] = value


class PromptsDumper(object):
    def __init__(self, dirpath):
        self.dirpath = dirpath
        self.yaml = YAML()
        self.yaml.default_flow_style = False
        self.yaml.allow_unicode = True
        self.yaml.indent(mapping=2, sequence=4, offset=2)

    @staticmethod
    def decodeEscapes(obj):
        if isinstance(obj, str):
            return LiteralScalarString(obj)
        elif isinstance(obj, dict):
            return {k: PromptsDumper.decodeEscapes(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [PromptsDumper.decodeEscapes(i) for i in obj]
        return obj

    @staticmethod
    def toDict(obj):
        if isinstance(obj, CommentedMap):
            return {k: PromptsDumper.toDict(v) for k, v in obj.items()}
        elif isinstance(obj, CommentedSeq):
            return [PromptsDumper.toDict(item) for item in obj]
        elif isinstance(obj, dict):
            return {k: PromptsDumper.toDict(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [PromptsDumper.toDict(item) for item in obj]
        else:
            return obj

    def check(self, round, name):
        yamlFile = os.path.join(self.dirpath, "{}".format(round), "{}.yaml".format(name))
        return os.path.exists(yamlFile)

    def load(self, round, name):
        yamlFile = os.path.join(self.dirpath, "{}".format(round), "{}.yaml".format(name))
        with open(yamlFile, "r", encoding="utf-8") as f:
            return PromptsDumper.toDict(self.yaml.load(f))

    def dump(self, round, name, resp):
        roundDir = os.path.join(self.dirpath, "{}".format(round))
        os.makedirs(roundDir, exist_ok=True)
        yamlFile = os.path.join(roundDir, "{}.yaml".format(name))
        with open(yamlFile, "w", encoding="utf-8") as f:
            self.yaml.dump(PromptsDumper.decodeEscapes(resp), f)
