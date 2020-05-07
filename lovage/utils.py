import os


def is_in_cloud():
    """
    Checks if this code is running in a deployed Lovage stack. Useful when you have to initialize global variables
    only in deployed code.
    :return: True if running in AWS/GCP/Azure/etc.
    """
    return os.getenv("LOVAGE_IN_CLOUD", "0") == "1"
