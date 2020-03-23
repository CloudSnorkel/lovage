import os
import traceback

import boto3
import cfnresponse


def handler(event, context):
    key = "BAD-PARAMETERS"

    try:
        key = event["ResourceProperties"]["Key"]
        bucket = os.environ['BUCKET']

        if event["RequestType"] in ["Create", "Update"]:
            print(f"Nothing to do for Create or Update")

        elif event["RequestType"] == "Delete":
            print(f"Deleting s3://{bucket}/{key}")

            try:
                boto3.client("s3").delete_object(Bucket=bucket, Key=key)
            except botocore.exceptions.ClientError:
                print(f"Error deleting {key}")
                try:
                    traceback.print_last()
                except ValueError:
                    print("Caught exception but unable to print stack trace")
                    print(e)

        result = {"Bucket": bucket, "Key": key}
        cfnresponse.send(event, context, cfnresponse.SUCCESS, result, key)
    except Exception as e:
        try:
            traceback.print_last()
        except ValueError:
            print("Caught exception but unable to print stack trace")
            print(e)
        cfnresponse.send(event, context, cfnresponse.FAILED, {}, key)
