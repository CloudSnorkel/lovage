import unittest

import boto3
import botocore.exceptions

from lovage.exceptions import LovageRemoteException


class TestFunctionException(unittest.TestCase):
    def test_basic(self):
        try:
            raise ValueError("hello world")
        except ValueError as e:
            le = LovageRemoteException.from_exception_object(LovageRemoteException.exception_object(e))
            assert le.exception == "ValueError"
            assert le.exception_fqn == "builtins.ValueError"
            assert e.args == le.args
            assert str(e) == str(le)

    def test_boto_exception(self):
        try:
            boto3.client("hello-world")
        except botocore.exceptions.UnknownServiceError as e:
            le = LovageRemoteException.from_exception_object(LovageRemoteException.exception_object(e))
            assert le.exception == "UnknownServiceError"
            assert le.exception_fqn == "botocore.exceptions.UnknownServiceError"
            assert e.args == le.args
            assert str(e) == str(le)
