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
from lovage.dirtools import Dir


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
        self._serializer = base.Serializer()  # TODO get from app
        if profile_name:
            self._session = boto3.Session(profile_name=profile_name)
        else:
            self._session = boto3.Session()
        self._executor = AwsLambdaExecutor(instance_name, self._serializer, self._session)
        self._additional_resources: typing.List[troposphere.BaseAWSObject] = []
        self._env: typing.Dict[str, object] = {"LOVAGE_IN_CLOUD": "1"}
        self._policies = []

    def new_task(self, func, options):
        desc = {
            "Name": _func_lambda_name(func, self._instance_name),
            "CfName": _func_cf_name(func),
            "Handler": "lovage.backends.awslambda.__init__.aws_router",
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
        return base.Task(func, self._executor, self._serializer)

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
            raise RuntimeError(f"Some files are missing from the packaged code, is root='{root}' the correct setting?")

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
        self._executor._exception_handler = handler

    def function_arn(self, func: types.FunctionType):
        return troposphere.GetAtt(_func_cf_name(func), "Arn")


class AwsLambdaExecutor(base.Executor):
    def __init__(self, instance_name: str, serializer: base.Serializer, session: boto3.Session):
        self._lambda = session.client("lambda")
        self._serializer = serializer
        self._name = instance_name
        self._exception_handler = _empty_exception_handler

    def invoke(self, func: types.FunctionType, packed_args):
        result = self._invoke(func, packed_args, "RequestResponse", 200)
        function_result = json.loads(result["Payload"].read())
        if "exception" in function_result:
            # TODO serialize stack trace
            # exceptions coming from here are not really from here, they're from the Lambda function
            raise self._serializer.unpack_result(base64.b85decode(function_result["exception"]))
        return base64.b85decode(function_result["result"])

    def invoke_async(self, func: types.FunctionType, packed_args):
        self._invoke(func, packed_args, "Event", 202)

    def _invoke(self, func: types.FunctionType, packed_args, invocation_type, required_status_code):
        result = self._lambda.invoke(
            FunctionName=_func_lambda_name(func, self._name),
            InvocationType=invocation_type,
            Payload=json.dumps({
                "serializer": _object_spec(self._serializer),
                "function": _function_spec(func),
                "exception_handler": _function_spec(self._exception_handler),
                "packed_args": base64.b85encode(packed_args).decode("utf-8"),
            }),
        )
        if result["StatusCode"] != required_status_code or result.get("FunctionError"):
            error = json.loads(result["Payload"].read())["errorMessage"]
            raise RuntimeError(f"Unhandled Lambda error for {func.__module__}.{func.__name__}: {error}")

        return result

    def queue(self, func: types.FunctionType, packed_args):
        raise NotImplementedError()

    def delay(self, func: types.FunctionType, packed_args, timeout):
        raise NotImplementedError()


def _load_object(spec):
    mod, name = spec.split(":")
    return getattr(importlib.import_module(mod), name)


def _object_spec(obj):
    return f"{obj.__module__}:{obj.__class__.__name__}"


def _func_lambda_name(func: types.FunctionType, instance_name):
    return f"{instance_name}-{_function_spec(func).replace('.', '-').replace(':', '--')}"


def _func_cf_name(func: types.FunctionType):
    return _function_spec(func).replace(".", "XdotX").replace(":", "XcolonX").replace("_", "XusX")


def _function_spec(func: types.FunctionType):
    if func.__module__ == "__main__":
        import __main__
        path = __main__.__file__
        relative = os.path.relpath(path, os.getcwd())  # TODO something better than cwd
        module_path = ".".join(os.path.split(os.path.splitext(relative)[0])).strip(".")
        return f"{module_path}:{func.__name__}"
    return f"{func.__module__}:{func.__name__}"


def _empty_exception_handler(e):
    pass


def aws_router(event, context):
    serializer = _load_object(event["serializer"])()
    func = _load_object(event["function"])
    exception_handler = _load_object(event["exception_handler"])
    args, kwargs = serializer.unpack_args(base64.b85decode(event["packed_args"]))
    try:
        result = func.call(*args, **kwargs)
    except Exception as e:
        exception_handler(e)
        packed_e = serializer.pack_result(e)
        return {"exception": base64.b85encode(packed_e).decode("utf-8")}
    packed_result = serializer.pack_result(result)
    return {"result": base64.b85encode(packed_result).decode("utf-8")}
