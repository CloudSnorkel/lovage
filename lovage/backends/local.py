import threading
import time
import types
import typing
from concurrent.futures.thread import ThreadPoolExecutor

from . import base


class LocalBackend(base.Backend):
    def __init__(self):
        self._serializer = base.Serializer()
        self._executor = LocalExecutor(self._serializer)

    def new_task(self, func: types.FunctionType, options):
        return base.Task(func, self._executor, self._serializer)

    def deploy(self, *, requirements: typing.List[str], root: str, exclude=None):
        print("Nothing to deploy when running locally")


class LocalExecutor(base.Executor):
    def __init__(self, serializer: base.Serializer):
        self._serializer = serializer
        self._executor = ThreadPoolExecutor(max_workers=1)

    def invoke(self, func: types.FunctionType, packed_args):
        unpacked_args, unpacked_kwargs = self._serializer.unpack_args(packed_args)
        result = func(*unpacked_args, **unpacked_kwargs)
        return self._serializer.pack_result(result)

    def invoke_async(self, func: types.FunctionType, packed_args):
        unpacked_args, unpacked_kwargs = self._serializer.unpack_args(packed_args)
        threading.Thread(target=func, args=unpacked_args, kwargs=unpacked_kwargs).start()

    def queue(self, func: types.FunctionType, packed_args):
        unpacked_args, unpacked_kwargs = self._serializer.unpack_args(packed_args)
        self._executor.submit(func, *unpacked_args, **unpacked_kwargs)

    def delay(self, func: types.FunctionType, packed_args, timeout):
        def delayer():
            time.sleep(timeout)
            self.invoke(func, packed_args)

        threading.Thread(target=delayer).start()
