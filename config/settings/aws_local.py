import logging

import boto3
import environ
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


def load_ssm_secrets(env: environ.Env, prefix: str = "/myapp"):
    """
    Load all SSM SecureString parameters under a given prefix
    and inject them into os.environ.

    Example:
        /myapp/DJANGO_SECRET_KEY -> os.environ['DJANGO_SECRET_KEY']
    """
    ssm = boto3.client("ssm", region_name=env("AWS_REGION", default="us-east-2"))  # pyright: ignore[reportArgumentType]
    try:
        # Fetch parameters by path
        paginator = ssm.get_paginator("get_parameters_by_path")
        for page in paginator.paginate(
            Path=prefix, WithDecryption=True, Recursive=True
        ):
            for param in page.get("Parameters", []):
                # Strip the prefix and any leading slash
                env_key = param["Name"].replace(prefix, "").lstrip("/").upper()
                env(env_key, param["Value"])
    except ClientError:
        errmsg = "Error loading SSM parameters"
        logger.exception(errmsg)
        raise
