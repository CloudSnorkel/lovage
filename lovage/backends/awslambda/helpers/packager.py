import hashlib
import json
import os
import platform
import shlex
import shutil
import subprocess
import traceback
import urllib.error
import urllib.request
import venv
import zipfile

import boto3

# TODO zip directly to s3 instead of /tmp first?

SUCCESS = "SUCCESS"
FAILED = "FAILED"


def cfn_response(event, context, status, physical_resource_id, data, reason=None):
    if reason:
        reason += "\n\n"
    else:
        reason = ""
    reason += f"See CloudWatch for details: {context.log_group_name} {context.log_stream_name}"

    response = json.dumps({
        "Status": status,
        "Reason": reason,
        "PhysicalResourceId": physical_resource_id,
        "StackId": event["StackId"],
        "RequestId": event["RequestId"],
        "LogicalResourceId": event["LogicalResourceId"],
        "Data": data or {}
    }).encode("utf-8")

    opener = urllib.request.build_opener(urllib.request.HTTPSHandler)
    request = urllib.request.Request(
        event["ResponseURL"],
        data=response,
        headers={
            "Content-Type": "",
            "Content-Length": f"{len(response)}"
        },
        method="PUT")
    opener.open(request)


def handler(event, context):
    pid = "BAD-PARAMETERS"

    try:
        requirements = _clean_requirements(event["ResourceProperties"]["Requirements"])
        hashed_data = requirements + " XX_VERSION_XX " + platform.python_version()
        rhash = hashlib.md5(hashed_data.encode("utf-8")).hexdigest()
        pid = f"req-{rhash}"
        key = f"requirements-{rhash}.zip"
        bucket = os.environ['BUCKET']

        if event["RequestType"] in ["Create", "Update"]:
            print(f"Installing on Python {platform.python_version()}: {requirements}...")

            shutil.rmtree("/tmp/venv", ignore_errors=True)
            shutil.rmtree("/tmp/python", ignore_errors=True)

            # we create a venv so package upgrades don't attempt read-only /var/runtime libraries
            venv.create("/tmp/venv", with_pip=True)
            cmd = f"/tmp/venv/bin/python -m pip --disable-pip-version-check install " \
                  f"-t /tmp/python --progress-bar off {requirements}"
            print(cmd)

            pip_result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if pip_result.returncode != 0:
                # response is limited to 4096 bytes total
                cfn_response(event, context, FAILED, pid, None,
                             f"pip failed [{pip_result.returncode}]:\n\n[...] {pip_result.stdout[-700:]}")
                return

            print(f"Building requirements package...")

            with zipfile.ZipFile("/tmp/python.zip", "w") as z:
                for root, folders, files in os.walk("/tmp/python"):
                    for f in files:
                        local_path = os.path.join(root, f)
                        zip_path = os.path.relpath(local_path, "/tmp")
                        z.write(local_path, zip_path, zipfile.ZIP_DEFLATED)

            print(f"Uploading to s3://{bucket}/{key}")

            boto3.client("s3").upload_file("/tmp/python.zip", bucket, key)

        elif event["RequestType"] == "Delete":
            print(f"Deleting s3://{bucket}/{key}")

            boto3.client('s3').delete_object(Bucket=bucket, Key=key)

        result = {"Bucket": bucket, "Key": key}
        cfn_response(event, context, SUCCESS, pid, result)
    except Exception as e:
        try:
            traceback.print_last()
        except ValueError:
            print("Caught exception but unable to print stack trace")
            print(e)
        cfn_response(event, context, FAILED, pid, None, str(e))


def _clean_requirements(requirements):
    result = ""
    for r in requirements:
        r = r.split("#")[0].strip()
        if r:
            result += f"{shlex.quote(r)} "
    return result
