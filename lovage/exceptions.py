import traceback


class LovageException(Exception):
    """
    Parent to all exceptions raised by Lovage.
    """
    pass


class LovageConfigurationError(LovageException):
    """
    Lovage configuration issue detected.
    """
    pass


class LovageDeploymentException(LovageException):
    """
    Deployment related errors.
    """
    pass


class LovageInternalException(LovageException):
    """
    Internal exception not related to user code.
    """
    pass


class LovageRemoteException(LovageException):
    """
    An exception describing an exception that was raised by the remote executed function.

    To get information about the original exception check out `exception` for the exception class name, `exception_fqn`
    for the fully qualified name, and `args` for the arguments the original exception had.
    """

    def __init__(self, exception, exception_fqn, exception_args, exception_str, stack_trace=None):
        # TODO copy stack trace
        super().__init__(*exception_args)
        self.exception = exception
        self.exception_fqn = exception_fqn
        self._str = exception_str

    def __str__(self):
        """
        :return: unmodified string representation of the remote exception
        """
        return self._str

    @staticmethod
    def exception_object(e: Exception):
        return {
            "exception": e.__class__.__name__,
            "exception_fqn": f"{e.__class__.__module__}.{e.__class__.__qualname__}",
            "exception_args": e.args,
            "exception_str": str(e),
        }

    @staticmethod
    def from_exception_object(o: dict):
        return LovageRemoteException(**o)
