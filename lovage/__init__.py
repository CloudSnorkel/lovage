import functools
import os

import lovage.backends
import lovage.backends.base


class Lovage(object):
    def __init__(self,
                 backend: lovage.backends.base.Backend = lovage.backends.LocalBackend(),
                 serializer: lovage.backends.base.Serializer = lovage.backends.base.Serializer()):
        self._backend = backend
        self._serializer = serializer

        self._functions = []

    def task(self, *args, **kwargs) -> lovage.backends.base.Task:
        def inner_create_task_cls(**opts):
            def _create_task_cls(func):
                task = self._backend.new_task(func, opts)
                return functools.update_wrapper(task, func)

            return _create_task_cls

        if len(args) == 1:
            if callable(args[0]):
                return inner_create_task_cls(**kwargs)(*args)
            raise TypeError('argument 1 to @task() must be a callable')
        if args:
            raise TypeError(f'@task() takes exactly 1 argument ({len(args) + len(kwargs)} given)')

        return inner_create_task_cls(**kwargs)

    def deploy(self, *, requirements="", exclude=None):
        if isinstance(requirements, str):
            requirements = [r.strip() for r in requirements.split("\n")]
        self._backend.deploy(requirements=requirements, exclude=exclude)

    def is_local_backend(self):
        """
        Checks if this app is configured to run locally.
        :return: True if default local backend is being used
        """
        return isinstance(self._backend, lovage.backends.LocalBackend)

    def is_in_cloud(self):
        """
        Checks if this code is running in a deployed Lovage stack. Useful when you have to initialize global variables
        only in deployed code.
        :return: True if running in AWS/GCP/Azure/etc.
        """
        return os.getenv("LOVAGE_IN_CLOUD", "0") == "1"
