# Initialize the SDKClient with AWS credentials
from sdk.auth import Auth
from sdk.aws_client import AwsClient
from sdk.epsilon_client import EpsilonClient


# AWS Example
try:
    auth = Auth(access_key="AKIA4NOSAVB26RXY2MVH", secret_key="24xIrreuxdIY49OLCzCBvRM2njOPde4mYpq+Cw+S")
    aws_client = AwsClient(auth,region_name = 'ap-northeast-2')
    bucket_name = "induk-cms"
    files = aws_client.file_list(bucket_name)
    print(f"AWS File List in {bucket_name}:", files)
except Exception as e:
    print(f"Error: {e}")


# Epsilon Example
try:
    auth = Auth(api_key="PMAK-6756e8f7c07fd40001d7f82c-67a33d75b1fb27a3483b9d51645aeda10c")
    epsilon_client = EpsilonClient(base_url="https://801415bc-219b-4a57-aed4-e7bf0ec4d6fd.mock.pstmn.io", auth=auth)
    files = epsilon_client.file_list()
    print(f"Epsilon File List :", files)
except Exception as e:
    print(f"Error: {e}")