import pickle
import typing
import types
import warnings


class Executor(object):
    def invoke(self, func: types.FunctionType, packed_args):
        raise NotImplementedError()

    def invoke_async(self, func: types.FunctionType, packed_args):
        raise NotImplementedError()

    def queue(self, func: types.FunctionType, packed_args):
        raise NotImplementedError()

    def delay(self, func: types.FunctionType, packed_args, timeout):
        raise NotImplementedError()


class Serializer(object):
    def __init__(self):
        self._serializer = pickle

    def pack_args(self, args, kwargs):
        return self._serializer.dumps({"args": args, "kwargs": kwargs})

    def unpack_args(self, packed_args):
        args = self._serializer.loads(packed_args)
        return args["args"], args["kwargs"]

    def pack_result(self, result):
        return self._serializer.dumps(result)

    def unpack_result(self, packed_result):
        return self._serializer.loads(packed_result)


class Task(object):
    def __init__(self, func: types.FunctionType, executor: Executor, serializer: Serializer):
        self._func = func
        self._executor = executor
        self._serializer = serializer

    def __call__(self, *args, **kwargs):
        warnings.warn(f"{self._func.__name__} called directly. Use .invoke(), .invoke_async(), .queue() or .delay() "
                      f"to take advantage of Lovage.",
                      stacklevel=2)
        return self._func(*args, **kwargs)

    def call(self, *args, **kwargs):
        return self._func(*args, **kwargs)

    def invoke(self, *args, **kwargs):
        packed_args = self._serializer.pack_args(args, kwargs)
        packed_result = self._executor.invoke(self._func, packed_args)
        return self._serializer.unpack_result(packed_result)

    def invoke_async(self, *args, **kwargs):
        packed_args = self._serializer.pack_args(args, kwargs)
        self._executor.invoke_async(self._func, packed_args)

    def queue(self, *args, **kwargs):
        packed_args = self._serializer.pack_args(args, kwargs)
        self._executor.queue(self._func, packed_args)

    def delay(self, timeout, *args, **kwargs):
        packed_args = self._serializer.pack_args(args, kwargs)
        self._executor.delay(self._func, packed_args, timeout)


class Backend(object):
    def new_task(self, func, options: typing.Mapping) -> Task:
        raise NotImplementedError()

    def deploy(self, *, requirements: typing.List[str], root: str, exclude=None):
        raise NotImplementedError()
