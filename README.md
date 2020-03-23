# Lovage

[![Actions Status](https://github.com/CloudSnorkel/lovage/workflows/Lovage%20build/badge.svg)](https://github.com/CloudSnorkel/lovage/actions)
[![PyPI](https://badge.fury.io/py/lovage.svg)](https://badge.fury.io/py/lovage)
[![PyPI pyversions](https://img.shields.io/pypi/pyversions/lovage.svg)](https://pypi.org/project/lovage/)
[![PyPI status](https://img.shields.io/pypi/status/lovage.svg)](https://pypi.org/project/lovage/)
[![GitHub stars](https://img.shields.io/github/stars/CloudSnorkel/lovage.svg?style=social&label=Star&maxAge=2592000)](https://GitHub.com/CloudSnorkel/lovage/stargazers/)

Python-only Serverless framework that's more RPC-like and less HTTP service oriented.

**Status:** Usable but not battle tested. PRs are welcome!

## Overview

Lovage is a serverless framework that makes it very easy to offload normal Python functions to the cloud.

### Call Functions Easily

Lovage lets you call functions without knowing anything about AWS API. You define the function as part of your codebase,
use `@app.task` decorator, deploy it, and then just call the function with `.invoke()` or `invoke_async()`. Function
arguments, return values, and exceptions can still be used as usual. You don't need to worry about serialization or AWS
API. Everything just works as it normally does with normal Python functions.

```python
import lovage.backends

app = lovage.Lovage(lovage.backends.AwsLambdaBackend("lovage-test"))


@app.task
def hello(x):
    return x + 1

if __name__ == "__main__":
    app.deploy(root=".", requirements=["requests"])
    print("hello.invoke(1) returned", hello.invoke(1))
```

### Compartmentalize Functions

It's easy to define separate IAM policies for each function to enhance your security with compartmentalization. You can
give granular access to each function to just the resources it needs.

```python
import boto3
import lovage.backends
import os.path

app = lovage.Lovage(lovage.backends.AwsLambdaBackend("lovage-test"))

# let this function send emails using SES as info@cloudsnorkel.com
EMAIL_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "ses:SendEmail",
            ],
            "Resource": "*",
            "Condition": {
                "StringEquals": {
                    "ses: FromAddress": "info@cloudsnorkel.com"
                }
            }
        }
    ]
}

@app.task(aws_policies=[EMAIL_POLICY])
def send_email(x):
    boto3.client("ses").send_email(Source="info@cloudsnorkel.com", ...)

if __name__ == "__main__":
    app.deploy(root=os.path.dirname(__file__), requirements=["boto3==1.12.25"])
    send_email.invoke_async()
```

### Requirements Layer Generated in Lambda

Unlike other solutions, Lovage collects and packages required libraries in Lambda itself. Each deployment has a custom
resource that gets the requirements list as a parameter, downloads all of them in Lambda, uploads it directly to S3, and
finally creates a Lambda layer containing all the dependencies. This gives you:

* Much faster cloud-local dependencies downloads and uploads
* No local development dependencies but Python (no need for Docker, no need to run on Linux, etc.)
* Faster code updates as you don't have to zip up the requirements and upload them along with your code
* Cleaner working directory with no dependencies being duplicated from your `site-packages` and no hidden folders

```python
import boto3
import lovage.backends

app = lovage.Lovage(lovage.backends.AwsLambdaBackend("lovage-test"))

if __name__ == "__main__":
    app.deploy(requirements=["boto3==1.12.25", "requests", "Django>=2.0.0"])
    # or...
    app.deploy(requirements=open("requirements.txt").read())
```

### Other Features

* CloudFormation stack leaves nothing behind and can be deleted without any special treatment
* Easy to test locally without deploying anything
* No need for Node.js
* Versatile configuration in code

## Usage

This script will deploy one function to AWS using Lambda, S3 and CloudFormation. It will then execute the function
twice. At first it will wait for the function to finish and print its answer. Then it will execute it asynchronously and
return control to your script immediately. 

```python
import lovage
import lovage.backends

app = lovage.Lovage(lovage.backends.AwsLambdaBackend("lovage-test"))


@app.task
def hello(x):
    print("hello world!")
    return x + 1


if __name__ == "__main__":
    app.deploy(requirements=[])
    print("hello.invoke(1) returned", hello.invoke(1))
    hello.invoke_async(2)
```

To delete the functions, simply delete the `lovage-test` CloudFormation stack. You can choose the name when creating the
`AwsLambdaBackend` object.

### Testing Locally

Sometimes you don't want to wait for a full deployment and just want to iterate locally. Lovage makes this simple with
`LocalBackend` which is the default backend. `app.deploy()` will do nothing and any function call will be executed
locally. When using `invoke_async()` a new thread will be created and the function will execute there.

```python
import platform

import lovage

app = lovage.Lovage()


@app.task
def hello():
    print("Hello locally from", platform.node())


if __name__ == "__main__":
    app.deploy()  # doesn't do anything
    hello.invoke()
```

### Ignoring Files

Lovage will package all files from the current working directory for the Lambda function and upload them for you. If you
want to avoid including some files because they are not required, you can create a file named `.lovageignore` which
works just like ce`.gitignore`. Any pattern listed there will be excluded from the package.

### Separate Environments

A common use-case in cloud development is having a separate environment for development, QA and production. Sometimes
even a separate environment for each developer. Lovage uses a self-contained CloudFormation stack for each environment.
There are no local or remote side-effects to worry about. As soon as you delete the stack, everything is gone.

The environment name is set by the first parameter given to `AwsLambdaBackend()`.

```python
app_dev = lovage.Lovage(lovage.backends.AwsLambdaBackend("lovage-dev"))
app_prod = lovage.Lovage(lovage.backends.AwsLambdaBackend("lovage-prod"))
```

*Caveat*: if you use `AwsLambdaBackend.add_resource()` to add additional CloudFormation resources to your stack, you may
have to delete those manually. For example, if you add a bucket, you have to make sure it's empty before deleting the
stack.

## Available Configuration

Configuration can be passed to the `@app.task()` decorator. For example:

```python
@app.task(timeout=30)
def hello_world():
  return 42
```

Some configuration is platform-specific and will therefore have a prefix like `aws_`.

| Configuration | Purpose | Default Value |
| ------------- |---------------|-------|
| `timeout` | Set Lambda timeout in seconds. Every Lambda function has a maximum execution time. | `3` |
| `aws_policies` | List of IAM policy documents to attach to the Lambda function. | `[]` |
| `aws_vpc_subnet_ids` | List of VPC subnets to attach to the Lambda function. Must be used together with `aws_vpc_security_group_ids`. | `[]` |
| `aws_vpc_security_group_ids` | List of VPC security groups to attach to the Lambda function. Must be used along with `aws_vpc_subnet_ids`. | `[]` |

## Best Practices

* Always specify `root` so you are sure which files are packaged. You can use something like `from pathlib import Path;
  app.deploy(root=Path(__file__).parent.parent)` to easily get your root folder.
* Always use `if __name__ == "__main__":` in files with Lovage tasks. Global code will be executed both locally and in
  Lambda. This may cause some unwanted side-effects.
* You should probably have a separate script to call `app.deploy()`. No-op deploys are pretty quick, but still take time
  to zip up the code, check if the latest is already available on S3, and finally update the CloudFormation stack.
