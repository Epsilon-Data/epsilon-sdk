import boto3
from sdk.auth import Auth
from sdk.iepsilon import IEpsilon
from sdk.errors import ClientError

class AwsClient(IEpsilon):
    def __init__(self, auth: Auth, region_name):
        self.auth = auth
        aws_credentials = auth.get_aws_credentials()
        self.s3 = boto3.client(
            "s3",
            aws_access_key_id=aws_credentials["access_key"],
            aws_secret_access_key=aws_credentials["secret_key"],
            region_name=region_name,
        )

    def file_list(self, bucket_name: str):
        try:
            response = self.s3.list_objects_v2(Bucket=bucket_name)
            return response.get("Contents", [])
        except Exception as e:
            raise ClientError(f"AWS file list operation failed: {str(e)}")

    def file_detail(self, bucket_name: str, file_key: str):
        try:
            response = self.s3.head_object(Bucket=bucket_name, Key=file_key)
            return response
        except Exception as e:
            raise ClientError(f"AWS file detail operation failed: {str(e)}")
