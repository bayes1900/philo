import os
import sys
from tqdm import tqdm
from datetime import datetime
from inspect import currentframe, getframeinfo


class BayesLogger(object):
    def __init__(self):
        self.logf = None
        self.verbose = True

    def __del__(self):
        if self.logf is not None:
            self.logf.close()

    def __header__(self, pid):
        now = datetime.now()
        frameInfo = getframeinfo(currentframe().f_back.f_back)
        if pid:
            return "[\033[90m{}|\033[0m{}:{}|{}] ".format(now.strftime("%Y-%m-%dT%H:%M:%S.%f"), os.path.basename(frameInfo.filename), frameInfo.lineno, os.getpid())
        return "[\033[90m{}|\033[0m{}:{}] ".format(now.strftime("%Y-%m-%dT%H:%M:%S.%f"), os.path.basename(frameInfo.filename), frameInfo.lineno)

    def setLogFile(self, filename):
        if self.logf is not None:
            self.logf.close()
        self.logf = open(filename, "w")

    def log(self, content, muted=False):
        if muted:
            return
        if self.logf is not None:
            self.logf.write(content + "\n")
            self.logf.flush()
            return
        tqdm.write(content, file=sys.stdout)

    def inf(self, line, *args, pid=False, muted=False):
        if not self.verbose:
            return
        if args:
            line = line.format(*args)
        self.log(self.__header__(pid) + line, muted)

    def grey(self, line, *args, pid=False, muted=False):
        if not self.verbose:
            return
        if args:
            line = line.format(*args)
        self.log("{}\033[90m{}\033[0m".format(self.__header__(pid), line), muted)

    def red(self, line, *args, pid=False, muted=False):
        if args:
            line = line.format(*args)
        self.log("{}\033[91m{}\033[0m".format(self.__header__(pid), line), muted)

    def green(self, line, *args, pid=False, muted=False):
        if not self.verbose:
            return
        if args:
            line = line.format(*args)
        self.log("{}\033[92m{}\033[0m".format(self.__header__(pid), line), muted)

    def yellow(self, line, *args, pid=False, muted=False):
        if args:
            line = line.format(*args)
        self.log("{}\033[93m{}\033[0m".format(self.__header__(pid), line), muted)

    def blue(self, line, *args, pid=False, muted=False):
        if not self.verbose:
            return
        if args:
            line = line.format(*args)
        self.log("{}\033[94m{}\033[0m".format(self.__header__(pid), line), muted)

    def pink(self, line, *args, pid=False, muted=False):
        if not self.verbose:
            return
        if args:
            line = line.format(*args)
        self.log("{}\033[95m{}\033[0m".format(self.__header__(pid), line), muted)

    def cyan(self, line, *args, pid=False, muted=False):
        if not self.verbose:
            return
        if args:
            line = line.format(*args)
        self.log("{}\033[96m{}\033[0m".format(self.__header__(pid), line), muted)


log = BayesLogger()
