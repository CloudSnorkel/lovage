import base64
import importlib
import inspect
import io
import json
import os.path
import types
import typing
import zipfile
from fnmatch import fnmatch

import boto3
import troposphere
import troposphere.awslambda

from lovage.backends import base
from lovage.backends.awslambda import cf
from lovage.backends.base import Serializer
from lovage.dirtools import Dir
from lovage.exceptions import LovageRemoteException, LovageDeploymentException, LovageInternalException
from lovage.utils import is_in_cloud


class ConsistentZipFile(zipfile.ZipFile):
    def add_file(self, local_path, zip_path):
        info = zipfile.ZipInfo(zip_path)
        # set permissions for windows machines so we don't get permission denied on Lambda
        info.external_attr = 0o755 << 16
        # force constant timestamp so same code produces same zip
        info.date_time = (2020, 1, 1, 0, 0, 0)
        self.writestr(info, open(local_path, "rb").read(), zipfile.ZIP_DEFLATED)


class AwsLambdaBackend(base.Backend):
    def __init__(self, instance_name: str, profile_name: str = None):
        self._instance_name = instance_name
        self._functions = []
        if profile_name and not is_in_cloud():
            self._session = boto3.Session(profile_name=profile_name)
        else:
            self._session = boto3.Session()
        self._executor = AwsLambdaExecutor(instance_name, self._session)
        self._additional_resources: typing.List[troposphere.BaseAWSObject] = []
        self._env: typing.Dict[str, object] = {"LOVAGE_IN_CLOUD": "1"}
        self._policies = []
        self._exception_handler = _empty_exception_handler

    def new_task(self, serializer: base.Serializer, func: types.FunctionType, options: typing.Mapping) -> base.Task:
        desc = {
            "Name": _func_lambda_name(func, self._instance_name),
            "CfName": _func_cf_name(func),
            "Handler": _function_lambda_spec(func),
            "Policies": options.get("aws_policies", []),
            "Kwargs": {},
            "OriginalFunction": func,
        }
        if "timeout" in options:
            desc["Kwargs"]["Timeout"] = options["timeout"]
        if "aws_vpc_subnet_ids" in options and "aws_vpc_security_group_ids" in options:
            desc["Kwargs"]["VpcConfig"] = troposphere.awslambda.VPCConfig(
                SubnetIds=options["aws_vpc_subnet_ids"],
                SecurityGroupIds=options["aws_vpc_security_group_ids"],
            )
            desc["Policies"].append({
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": [
                            "ec2:CreateNetworkInterface"
                        ],
                        "Resource": "*"
                    },
                    {
                        "Effect": "Allow",
                        "Action": [
                            "ec2:DescribeNetworkInterfaces",
                            "ec2:DeleteNetworkInterface"
                        ],
                        "Resource": "*"
                        # troposphere.Sub("arn:${AWS::Partition}:ec2:${AWS::Region}:${AWS::AccountId}:network-interface/*")
                    }
                ]
            })
        elif "aws_vpc_security_group_ids" in options or "aws_vpc_subnet_ids" in options:
            raise ValueError("aws_vpc_security_group_ids and aws_vpc_security_group_ids must be used together")
        self._functions.append(desc)
        return AwsTask(func, self._executor, serializer, self._exception_handler)

    def deploy(self, *, requirements: typing.List[str], root: str, exclude=None):
        # TODO allow configuration of this
        # all files in CWD
        # all files in certain directory
        # all python files
        # git archive
        # .gitignore?
        # serverless way
        zs = io.BytesIO()
        packaged_modules = set()
        with ConsistentZipFile(zs, "w") as z:
            exclude = exclude or []
            for walk_root, folders, files in Dir(directory=root, excludes=exclude, exclude_file=".lovageignore").walk():
                for f in files:
                    local_path = os.path.join(walk_root, f)
                    zip_path = os.path.relpath(local_path, '.')
                    z.add_file(local_path, zip_path)
                    packaged_modules.add(os.path.abspath(local_path))

            from lovage import __version__ as lovage_version
            if lovage_version != "0.0.0":
                # prepend requirements to allow user to override
                requirements.insert(0, f"lovage=={lovage_version}")
            else:
                print("Unable to find Lovage version, using local files (can happen while developing Lovage)")
                # lovage dependencies
                requirements.insert(0, "troposphere")
                requirements.insert(1, "globster==0.1.0")

                import lovage
                lovage_dir = os.path.dirname(os.path.dirname(lovage.__file__))

                for walk_root, folders, files in os.walk(lovage_dir):
                    for f in files:
                        local_path = os.path.join(walk_root, f)
                        zip_path = os.path.relpath(local_path, lovage_dir)
                        if fnmatch(zip_path, "lovage/*.py"):
                            z.add_file(local_path, zip_path)

        zs.seek(0)
        zip_bytes = zs.read()

        missing_files = False
        for fd in self._functions:
            f = fd["OriginalFunction"]
            fm = os.path.abspath(inspect.getfile(f))
            if fm not in packaged_modules:
                print(f"{inspect.getmodule(f).__name__}.{f.__name__} is defined in {fm} but it was not packaged")
                missing_files = True

        if missing_files:
            raise LovageDeploymentException(f"Some files are missing from the packaged code, "
                                            f"is root='{root}' the correct setting?")

        cf.deploy(self._session, self._instance_name, zip_bytes, requirements,
                  self._functions, self._additional_resources, self._env, self._policies)

    def add_resource(self, resource: troposphere.BaseAWSObject):
        # TODO better name than resource since this can be output too?
        self._additional_resources.append(resource)

    def add_environment_variable(self, name: str, value):
        # TODO do something that works for local, aws, gcp, etc.
        self._env[name] = value

    def add_common_policy(self, policy):
        self._policies.append(policy)

    def set_exception_handler(self, handler: typing.Callable[[Exception], None]):
        self._exception_handler = handler

    def function_arn(self, func: types.FunctionType):
        return troposphere.GetAtt(_func_cf_name(func), "Arn")


class AwsLambdaExecutor(base.Executor):
    def __init__(self, instance_name: str, session: boto3.Session):
        self._lambda = session.client("lambda")
        self._name = instance_name

    def invoke(self, serializer: base.Serializer, func: types.FunctionType, packed_args):
        result = self._invoke(func, packed_args, "RequestResponse", 200)
        function_result = json.loads(result["Payload"].read())
        if "exception" in function_result:
            # TODO serialize stack trace
            # exceptions coming from here are not really from here, they're from the Lambda function
            exception_data = serializer.unpack_result(base64.b85decode(function_result["exception"]))
            if serializer.objects_supported:
                raise exception_data  # exception from the Lambda function
            else:
                raise LovageRemoteException.from_exception_object(exception_data)  # exception from the Lambda function
        return base64.b85decode(function_result["result"])

    def invoke_async(self, serializer: base.Serializer, func: types.FunctionType, packed_args):
        self._invoke(func, packed_args, "Event", 202)

    def _invoke(self, func: types.FunctionType, packed_args, invocation_type: str, required_status_code: int):
        result = self._lambda.invoke(
            FunctionName=_func_lambda_name(func, self._name),
            InvocationType=invocation_type,
            Payload=json.dumps({
                "packed_args": base64.b85encode(packed_args).decode("utf-8"),
            }),
        )
        if result["StatusCode"] != required_status_code or result.get("FunctionError"):
            error = json.loads(result["Payload"].read())["errorMessage"]
            raise LovageInternalException(f"Unhandled Lambda error for {func.__module__}.{func.__name__}: {error}")

        return result

    def queue(self, serializer: base.Serializer, func: types.FunctionType, packed_args):
        raise NotImplementedError()

    def delay(self, serializer: base.Serializer, func: types.FunctionType, packed_args, timeout):
        raise NotImplementedError()


class AwsTask(base.Task):
    def __init__(self, func: types.FunctionType, executor: AwsLambdaExecutor, serializer: Serializer,
                 exception_handler: typing.Callable[[Exception], None]):
        super().__init__(func, executor, serializer)
        self._exception_handler = exception_handler

    def __call__(self, *args, **kwargs):
        if not is_in_cloud():
            super().call(*args, **kwargs)
        else:
            # this assumes we have the same backend settings here as we do when this was deployed.
            # we use to just tell lambda which serializer, exception handler and function to dynamically load, but this
            # solution was not secure. users can force lambda to execute arbitrary code this way.
            # TODO verify same backend settings with a hash or something?
            event, context = args
            args, kwargs = self._serializer.unpack_args(base64.b85decode(event["packed_args"]))
            try:
                result = self._func(*args, **kwargs)
            except Exception as e:
                self._exception_handler(e)
                if self._serializer.objects_supported:
                    packed_e = self._serializer.pack_result(e)
                else:
                    packed_e = self._serializer.pack_result(LovageRemoteException.exception_object(e))
                return {"exception": base64.b85encode(packed_e).decode("utf-8")}
            packed_result = self._serializer.pack_result(result)
            return {"result": base64.b85encode(packed_result).decode("utf-8")}


def _func_lambda_name(func: types.FunctionType, instance_name) -> str:
    return f"{instance_name}-{_function_spec(func).replace('.', '-').replace(':', '--')}"


def _func_cf_name(func: types.FunctionType) -> str:
    return _function_spec(func).replace(".", "XdotX").replace(":", "XcolonX").replace("_", "XusX")


def _function_lambda_spec(func: types.FunctionType) -> str:
    return _function_spec(func).replace(":", ".")


def _function_spec(func: types.FunctionType) -> str:
    if func.__module__ == "__main__":
        import __main__
        path = __main__.__file__
        relative = os.path.relpath(path, os.getcwd())  # TODO something better than cwd
        module_path = ".".join(os.path.split(os.path.splitext(relative)[0])).strip(".")
        return f"{module_path}:{func.__name__}"
    return f"{func.__module__}:{func.__name__}"


def _empty_exception_handler(e):
    pass

