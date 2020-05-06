import time
import unittest

import lovage
from lovage.exceptions import LovageRemoteException


class SomeException(Exception):
    pass


class TestLocal(unittest.TestCase):
    def test_basic(self):
        app = lovage.Lovage()

        @app.task
        def hello_world():
            return 42

        assert hello_world.invoke() == 42

    def test_async(self):
        app = lovage.Lovage()
        hello = []

        @app.task
        def hello_world():
            hello.append("world")

        hello_world.invoke_async()
        time.sleep(1)
        assert hello == ["world"]

    def test_json_exception(self):
        app = lovage.Lovage()

        @app.task
        def hello_world():
            raise SomeException()

        with self.assertRaises(LovageRemoteException) as cm:
            hello_world.invoke()

        assert cm.exception.exception == "SomeException"
        assert cm.exception.exception_fqn == "test_basic.SomeException"
        assert cm.exception.args == tuple()
        assert str(cm.exception) == str(SomeException())

    def test_pickle_exception(self):
        app = lovage.Lovage(serializer=lovage.backends.PickleSerializer())

        @app.task
        def hello_world():
            raise SomeException()

        with self.assertRaises(SomeException):
            hello_world.invoke()

    def test_queue(self):
        app = lovage.Lovage()
        hello = []

        @app.task
        def hello_world():
            time.sleep(0.1)
            hello.append("world")

        hello_world.queue()
        hello_world.queue()
        hello_world.queue()

        assert len(hello) < 3
        time.sleep(1)
        assert len(hello) == 3

    def test_delay(self):
        app = lovage.Lovage()
        hello = []

        @app.task
        def hello_world():
            hello.append("world")

        hello_world.delay(1)
        assert hello == []
        time.sleep(2)
        assert hello == ["world"]

    def test_object_serializer_error(self):
        app = lovage.Lovage()

        @app.task
        def hello_world(x):
            print(x)

        class SomeObject(object):
            pass

        with self.assertRaises(RuntimeError) as cm:
            hello_world.invoke(SomeObject())

        assert "The default serializer doesn't support objects" in cm.exception.args[0]
