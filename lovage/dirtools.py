# taken from https://github.com/tsileo/dirtools/
# updated for Python 3 and removed stuff we don't need

import logging
import os

from globster import Globster

log = logging.getLogger("dirtools")


# TODO abs=True args for .files(), .subdirs() ?


def load_patterns(exclude_file=".exclude"):
    """ Load patterns to exclude file from `exclude_file',
    and return a list of pattern.

    :type exclude_file: str
    :param exclude_file: File containing exclude patterns

    :rtype: list
    :return: List a patterns

    """
    return filter(None, open(exclude_file).read().split("\n"))


class Dir(object):
    """ Wrapper for dirtools arround a path.

    Try to load a .exclude file, ready to compute hashdir,


    :type directory: str
    :param directory: Root directory for initialization

    :type exclude_file: str
    :param exclude_file: File containing exclusion pattern,
        .exclude by default, you can also load .gitignore files.

    :type excludes: list
    :param excludes: List of additionals patterns for exclusion,
        by default: ['.git/', '.hg/', '.svn/']

    """

    def __init__(self, directory=".", exclude_file=".exclude",
                 excludes=['.git/', '.hg/', '.svn/'], includes=[]):
        if not os.path.isdir(directory):
            raise TypeError("Directory must be a directory.")
        self.directory = os.path.basename(directory)
        self.path = os.path.abspath(directory)
        self.parent = os.path.dirname(self.path)
        self.exclude_file = os.path.join(self.path, exclude_file)
        self.patterns = excludes
        if os.path.isfile(self.exclude_file):
            self.patterns.extend(load_patterns(self.exclude_file))
        self.globster = Globster(self.patterns)

    def is_excluded(self, path):
        """ Return True if `path' should be excluded
        given patterns in the `exclude_file'. """
        match = self.globster.match(self.relpath(path))
        if match:
            log.debug("{0} matched {1} for exclusion".format(path, match))
            return True
        return False

    def walk(self):
        """ Walk the directory like os.path
        (yields a 3-tuple (dirpath, dirnames, filenames)
        except it exclude all files/directories on the fly. """
        for root, dirs, files in os.walk(self.path, topdown=True):
            # TODO relative walk, recursive call if root excluder found???
            # root_excluder = get_root_excluder(root)
            ndirs = []
            # First we exclude directories
            for d in list(dirs):
                if self.is_excluded(os.path.join(root, d)):
                    dirs.remove(d)
                elif not os.path.islink(os.path.join(root, d)):
                    ndirs.append(d)

            nfiles = []
            for fpath in (os.path.join(root, f) for f in files):
                if not self.is_excluded(fpath) and not os.path.islink(fpath):
                    nfiles.append(os.path.relpath(fpath, root))

            yield root, ndirs, nfiles

    def relpath(self, path):
        """ Return a relative filepath to path from Dir path. """
        return os.path.relpath(path, start=self.path)
