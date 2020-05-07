import json
import pickle
import types
import typing
import warnings

from lovage.exceptions import LovageException, LovageConfigurationError
from lovage.utils import is_in_cloud

class Serializer(object):
    def __init__(self):
        self.objects_supported = False

    def pack_args(self, args, kwargs):
        return self._serialize({"args": args, "kwargs": kwargs})

    def unpack_args(self, packed_args):
        args = self._deserialize(packed_args)
        return args["args"], args["kwargs"]

    def pack_result(self, result):
        return self._serialize(result)

    def unpack_result(self, packed_result):
        return self._deserialize(packed_result)

    def _serialize(self, obj: typing.Any) -> bytes:
        raise NotImplementedError()

    def _deserialize(self, data: bytes) -> typing.Any:
        raise NotImplementedError()


class PickleSerializer(Serializer):
    def __init__(self):
        super().__init__()
        self.objects_supported = True

    def _serialize(self, obj: typing.Any) -> bytes:
        return pickle.dumps(obj)

    def _deserialize(self, data: bytes) -> typing.Any:
        return pickle.loads(data)


class JSONSerializer(Serializer):
    # TODO turn this into hybrid serializer that uses JSON for incoming and pickle for outgoing?
    # TODO how can we support exceptions?
    def _serialize(self, obj: typing.Any) -> bytes:
        try:
            return json.dumps(obj).encode("utf-8")
        except (TypeError, ValueError) as e:
            suggestion = "The default serializer doesn't support objects. If you need to pass objects, trust all the " \
                         "code that can call functions, and understand the risks of pickle, use app = lovage.Lovage(" \
                         "serializer=lovage.backends.PickleSerializer()) "
            raise LovageException(suggestion) from e  # TODO better exception type here

    def _deserialize(self, data: bytes) -> typing.Any:
        return json.loads(data.decode("utf-8"))


class Executor(object):
    def invoke(self, serializer: Serializer, func: types.FunctionType, packed_args):
        raise NotImplementedError()

    def invoke_async(self, serializer: Serializer, func: types.FunctionType, packed_args):
        raise NotImplementedError()

    def queue(self, serializer: Serializer, func: types.FunctionType, packed_args):
        raise NotImplementedError()

    def delay(self, serializer: Serializer, func: types.FunctionType, packed_args, timeout):
        raise NotImplementedError()


class Task(object):
    def __init__(self, func: types.FunctionType, executor: Executor, serializer: Serializer):
        self._func = func
        self._executor = executor
        self._serializer = serializer

    def __call__(self, *args, **kwargs):
        if is_in_cloud():
            raise LovageConfigurationError("Local backend used in cloud deployment. Make sure the right cloud backend "
                                           "is used in the code that runs in the cloud.")

        warnings.warn(f"{self._func.__name__} called directly. Use .invoke(), .invoke_async(), .queue() or .delay() "
                      f"to take advantage of Lovage.",
                      stacklevel=2)
        return self._func(*args, **kwargs)

    def call(self, *args, **kwargs):
        return self._func(*args, **kwargs)

    def invoke(self, *args, **kwargs):
        packed_args = self._serializer.pack_args(args, kwargs)
        packed_result = self._executor.invoke(self._serializer, self._func, packed_args)
        return self._serializer.unpack_result(packed_result)

    def invoke_async(self, *args, **kwargs):
        packed_args = self._serializer.pack_args(args, kwargs)
        self._executor.invoke_async(self._serializer, self._func, packed_args)

    def queue(self, *args, **kwargs):
        packed_args = self._serializer.pack_args(args, kwargs)
        self._executor.queue(self._serializer, self._func, packed_args)

    def delay(self, timeout, *args, **kwargs):
        packed_args = self._serializer.pack_args(args, kwargs)
        self._executor.delay(self._serializer, self._func, packed_args, timeout)


class Backend(object):
    def new_task(self, serializer: Serializer, func: types.FunctionType, options: typing.Mapping) -> Task:
        raise NotImplementedError()

    def deploy(self, *, requirements: typing.List[str], root: str, exclude=None):
        raise NotImplementedError()
