import threading
import time
import types
import typing
from concurrent.futures.thread import ThreadPoolExecutor

from . import base
from ..exceptions import LovageRemoteException


class LocalBackend(base.Backend):
    def __init__(self):
        self._executor = LocalExecutor()

    def new_task(self, serializer: base.Serializer, func: types.FunctionType, options: typing.Mapping) -> base.Task:
        return base.Task(func, self._executor, serializer)

    def deploy(self, *, requirements: typing.List[str], root: str, exclude=None):
        print("Nothing to deploy when running locally")


class LocalExecutor(base.Executor):
    def __init__(self):
        self._executor = ThreadPoolExecutor(max_workers=1)

    def invoke(self, serializer: base.Serializer, func: types.FunctionType, packed_args):
        return self._invoke(serializer, func, packed_args)

    def invoke_async(self, serializer: base.Serializer, func: types.FunctionType, packed_args):
        threading.Thread(target=self._invoke, args=(serializer, func, packed_args)).start()

    def queue(self, serializer: base.Serializer, func: types.FunctionType, packed_args):
        self._executor.submit(self._invoke, serializer, func, packed_args)

    def delay(self, serializer: base.Serializer, func: types.FunctionType, packed_args, timeout):
        def delayer():
            time.sleep(timeout)
            self._invoke(serializer, func, packed_args)

        threading.Thread(target=delayer).start()

    @staticmethod
    def _invoke(serializer: base.Serializer, func: types.FunctionType, packed_args):
        # TODO handle exceptions so we can test serializers
        try:
            unpacked_args, unpacked_kwargs = serializer.unpack_args(packed_args)
            result = func(*unpacked_args, **unpacked_kwargs)
            return serializer.pack_result(result)
        except Exception as e:
            # exception_handler(e) -- TODO AWS only for now
            if serializer.objects_supported:
                packed_e = serializer.pack_result(e)
                unpacked_e = serializer.unpack_result(packed_e)
                raise unpacked_e
            else:
                raise LovageRemoteException.from_exception_object(LovageRemoteException.exception_object(e))
