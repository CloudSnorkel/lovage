import hashlib
import os
import platform
import shlex
import shutil
import traceback
import venv
import zipfile

import boto3
import cfnresponse


# TODO zip directly to s3 instead of /tmp first?

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
            cmd = f"/tmp/venv/bin/python -m pip install -t /tmp/python --progress-bar off {requirements}"
            print(cmd)

            if os.system(cmd) != 0:
                raise RuntimeError("pip failed")

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
        cfnresponse.send(event, context, cfnresponse.SUCCESS, result, pid)
    except Exception as e:
        try:
            traceback.print_last()
        except ValueError:
            print("Caught exception but unable to print stack trace")
            print(e)
        cfnresponse.send(event, context, cfnresponse.FAILED, {}, pid)


def _clean_requirements(requirements):
    result = ""
    for r in requirements:
        r = r.split("#")[0].strip()
        if r:
            result += f"{shlex.quote(r)} "
    return result
