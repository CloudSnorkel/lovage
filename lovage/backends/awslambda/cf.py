import contextlib
import hashlib
import pkgutil
import platform
import re
import typing

import boto3
import botocore.exceptions
import troposphere.awslambda
import troposphere.cloudformation
import troposphere.iam
import troposphere.logs
import troposphere.s3

# handle python version
# TODO share boto3 session and use profile name if needed

REQUIREMENTS_LAYER_PACKAGER_CODE = pkgutil.get_data('lovage', 'backends/awslambda/helpers/packager.py').decode('utf-8')
CODE_DELETER_CODE = pkgutil.get_data('lovage', 'backends/awslambda/helpers/deleter.py').decode('utf-8')
assert REQUIREMENTS_LAYER_PACKAGER_CODE and CODE_DELETER_CODE


def _alphanumeric_name(name):
    return re.sub("[^a-zA-Z0-9]", "X", name)


class RequirementsLayerPackage(troposphere.cloudformation.AWSCustomObject):
    resource_type = "Custom::RequirementsLayerPackage"

    props = {
        'ServiceToken': (str, True),
    }


def _add_log_group(template: troposphere.Template, cf_name: str, name: str):
    return troposphere.logs.LogGroup(
        f"{cf_name}LogGroup",
        template,
        LogGroupName=troposphere.Sub(f"/aws/lambda/{name}"),
        RetentionInDays=30,  # TODO config
    )


def _get_python_runtime():
    # https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html#w503aac27c25
    v = platform.python_version_tuple()
    vs = f"python{v[0]}.{v[1]}"
    if vs in ("python3.6", "python3.7", "python3.8"):
        return vs
    raise RuntimeError(f"{vs} is not supported in AWS Lambda")


def _add_lambda(template: troposphere.Template, cf_name: str, name: str, policies: typing.List[troposphere.iam.Policy],
                **kwargs) -> troposphere.awslambda.Function:
    log_group = _add_log_group(template, cf_name, name)
    log_policy = troposphere.iam.Policy(
        PolicyName="Log",
        PolicyDocument={
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": [
                        "logs:CreateLogGroup",
                        "logs:CreateLogStream",
                        "logs:PutLogEvents",
                    ],
                    "Resource": [
                        troposphere.Sub(f"${{{log_group.title}.Arn}}"),
                        troposphere.Sub(f"${{{log_group.title}.Arn}}/*"),
                    ],
                },
            ]
        }
    )

    role = troposphere.iam.Role(f"{cf_name}Role", template)
    role.AssumeRolePolicyDocument = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Service": [
                        troposphere.Sub("lambda.${AWS::URLSuffix}")
                    ]
                },
                "Action": [
                    "sts:AssumeRole"
                ]
            }
        ],
    }
    role.Policies = [log_policy] + policies

    func = troposphere.awslambda.Function(cf_name, template, **kwargs)
    if '${' in name:
        func.FunctionName = troposphere.Sub(name)
    else:
        func.FunctionName = name
    func.Runtime = _get_python_runtime()
    func.Role = role.get_att("Arn")
    func.DependsOn = [log_group.title]

    return func


def _add_str_lambda(template: troposphere.Template, name: str, code: str, policies: typing.List[troposphere.iam.Policy],
                    **kwargs):
    return _add_lambda(
        template, name, f"${{AWS::StackName}}-{name}", policies,
        Code=troposphere.awslambda.Code(ZipFile=code),
        Handler="index.handler",
        **kwargs
    )


def _add_codezip_lambda(template, cf_name, name, code, policies, **kwargs) -> troposphere.awslambda.Function:
    return _add_lambda(
        template, cf_name, name, policies,
        Code=troposphere.awslambda.Code(
            S3Bucket=troposphere.Sub(f"${{{code.title}.Bucket}}"),
            S3Key=troposphere.Sub(f"${{{code.title}.Key}}"),
        ),
        **kwargs
    )


class CodePackage(troposphere.cloudformation.AWSCustomObject):
    resource_type = "Custom::CodePackage"

    props = {
        'ServiceToken': (str, True),
    }


def _add_code(template, bucket, code_key):
    code_deleter = _add_str_lambda(
        template,
        "CodeDeleter",
        CODE_DELETER_CODE,
        [
            troposphere.iam.Policy(
                PolicyName="DeleteCode",
                PolicyDocument={
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Action": [
                                "s3:DeleteObject",
                            ],
                            "Resource": troposphere.Sub("${LovageBucket.Arn}/code-*.zip"),
                        },
                    ]
                }
            )
        ],
        Environment=troposphere.awslambda.Environment(
            Variables={
                "BUCKET": bucket.ref(),
            }
        ),
        Description="Deletes code packages from bucket so bucket can be easily deleted",
    )

    return CodePackage(
        "CodePackage",
        template,
        ServiceToken=code_deleter.get_att("Arn"),
        Key=code_key,
    )


def _stub_template():
    template = troposphere.Template()

    bucket = troposphere.s3.Bucket(
        "LovageBucket",
        template
    )

    return bucket, template


def generate_stub_template():
    _, template = _stub_template()
    return template.to_yaml(clean_up=True, long_form=True)


def generate_template(stack_name: str, bucket_name: str, code_key: str, requirements: typing.List[str],
                      functions: typing.Sequence[typing.Mapping],
                      resources: typing.Sequence[troposphere.BaseAWSObject],
                      env: typing.Dict[str, object],
                      policies: typing.Sequence):
    bucket, template = _stub_template()

    packager = _add_str_lambda(
        template,
        "RequirementsPackager",
        REQUIREMENTS_LAYER_PACKAGER_CODE,
        [
            troposphere.iam.Policy(
                PolicyName="SaveLayer",
                PolicyDocument={
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Action": [
                                "s3:PutObject",
                                "s3:DeleteObject",
                            ],
                            "Resource": troposphere.Sub("${LovageBucket.Arn}/requirements-*.zip"),
                        },
                    ]
                }
            )
        ],
        Environment=troposphere.awslambda.Environment(
            Variables={
                "BUCKET": bucket.ref()
            }
        ),
        Timeout=15 * 60,
        MemorySize=1024,
        Description="Downloads Python requirements, zips them, and uploads to a bucket to be used by Lambda layer",
    )

    package = RequirementsLayerPackage(
        "RequirementsPackage",
        template,
        ServiceToken=packager.get_att("Arn"),
        Requirements=requirements,
        # we need to rebuild requirements.zip if python version changes because it might install different libraries
        PythonVersion=_get_python_runtime(),
    )

    layer = troposphere.awslambda.LayerVersion(
        f"{_alphanumeric_name(stack_name)}RequirementsLayer",
        template,
        Content=troposphere.awslambda.Content(
            S3Bucket=troposphere.Sub(f"${{{package.title}.Bucket}}"),
            S3Key=troposphere.Sub(f"${{{package.title}.Key}}"),
        )
    )

    code = _add_code(template, bucket, code_key)

    for f in functions:
        lf = _add_codezip_lambda(
            template,
            f["CfName"],
            f["Name"],
            code,
            [
                troposphere.iam.Policy(
                    PolicyName=f"Custom{i}",
                    PolicyDocument=p)
                for i, p in enumerate(policies + f["Policies"])
            ],
            Layers=[layer.ref()],
            Handler=f["Handler"],
            **f["Kwargs"],
        )

        lf.Environment = troposphere.awslambda.Environment(Variables=env)

    for r in resources:
        template.add_resource(r)

    return template.to_yaml(clean_up=True, long_form=True)


def _stack_exists(cf, name):
    try:
        cf.describe_stacks(StackName=name)
        return True
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "ValidationError":
            return False
        raise


@contextlib.contextmanager
def _code_uploader(bucket, code_bytes):
    print("Uploading code...")

    code_hash = hashlib.md5(code_bytes).hexdigest()
    code_key = f"code-{code_hash}.zip"

    delete_on_failure = False

    s3 = boto3.client('s3')

    try:
        s3.head_object(Bucket=bucket, Key=code_key)
        print("Code already uploaded")
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "404":
            s3.put_object(Body=code_bytes, Bucket=bucket, Key=code_key, ContentType="application/zip")
            # only delete on failure if we uploaded the code and it's not the old code
            delete_on_failure = True
        else:
            raise

    try:

        yield code_key

    except Exception:
        if delete_on_failure:
            try:
                s3.delete_object(Bucket=bucket, Key=code_key)
                print("Code already uploaded")
            except botocore.exceptions.ClientError as e:
                print("Error while deleting code package", e)

        raise


def wait_and_log(cf, waiter, stack_name):
    try:
        cf.get_waiter(waiter).wait(StackName=stack_name)
        return
    except botocore.exceptions.WaiterError as e:
        # TODO check that e is stack failure and not something else
        reason = f"Stack {stack_name} failed to deploy due to:"
        for events_page in cf.get_paginator("describe_stack_events").paginate(StackName=stack_name):
            for event in events_page["StackEvents"]:
                if event["LogicalResourceId"] == stack_name and event.get("ResourceStatusReason") == "User Initiated" \
                        and event["ResourceStatus"] in ["UPDATE_IN_PROGRESS", "CREATE_IN_PROGRESS"]:
                    raise RuntimeError(reason) from None
                if event["ResourceStatus"] in ["CREATE_FAILED", "DELETE_FAILED", "UPDATE_FAILED"]:
                    if not event["ResourceStatusReason"]:
                        # empty error
                        continue
                    if event["ResourceStatusReason"] == "Resource update cancelled":
                        # this "error" doesn't help debugging
                        continue
                    reason += "\n  %(LogicalResourceId)s | %(ResourceStatus)s | %(ResourceStatusReason)s" % event
        raise RuntimeError(reason) from None


def deploy(session: boto3.Session, stack_name: str, code_bytes: bytes, requirements: typing.List[str],
           functions: typing.Sequence[typing.Mapping],
           resources: typing.Sequence[troposphere.BaseAWSObject],
           env: typing.Dict[str, object],
           policies: typing.Sequence):
    cf = session.client("cloudformation")

    if not _stack_exists(cf, stack_name):
        print("Creating stub stack...")
        cf.create_stack(
            StackName=stack_name,
            TemplateBody=generate_stub_template(),
            Tags=[
                {
                    "Key": "Lovage",
                    "Value": "true",  # TODO version?
                },
            ],
        )

        wait_and_log(cf, "stack_create_complete", stack_name)

    for t in cf.describe_stacks(StackName=stack_name)["Stacks"][0]["Tags"]:
        if t["Key"] == "Lovage":
            break
    else:
        raise ValueError(f"Stack `{stack_name}` already exists. Use a different deployment name.")

    bucket = cf.describe_stack_resource(
        StackName=stack_name, LogicalResourceId="LovageBucket")["StackResourceDetail"]["PhysicalResourceId"]

    try:
        with _code_uploader(bucket, code_bytes) as code_key:
            print("Updating stack...")
            cf.update_stack(
                StackName=stack_name,
                TemplateBody=generate_template(stack_name, bucket, code_key, requirements,
                                               functions, resources, env, policies),
                Capabilities=["CAPABILITY_IAM"],
                Parameters=[],
            )

            wait_and_log(cf, "stack_update_complete", stack_name)
    except botocore.exceptions.ClientError as e:
        if e.response['Error']['Code'] == 'ValidationError' \
                and e.response['Error']['Message'] == 'No updates are to be performed.':
            print("Stack already up-to-date")
            return
        raise
