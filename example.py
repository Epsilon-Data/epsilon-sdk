# Initialize the SDKClient with AWS credentials
from sdk.auth import Auth
from sdk.aws_client import AwsClient


# AWS Example
try:
    auth = Auth(access_key="", secret_key="")
    aws_client = AwsClient(auth,region_name = 'ap-northeast-2')
    bucket_name = ""
    files = aws_client.file_list(bucket_name)
    print(f"AWS File List in {bucket_name}:", files)
except Exception as e:
    print(f"Error: {e}")
