#!/bin/bash

# Build script for AWS Lambda deployment package

echo "Building Lambda deployment package..."

# Clean up previous builds
rm -rf package/
rm -f lambda_deployment.zip

# Create package directory
mkdir package

# Install runtime dependencies only (test deps live in requirements-dev.txt).
# boto3/botocore are provided by the Lambda runtime, so exclude them from the
# package to keep the zip small. They stay in requirements.txt for local dev.
# anthropic depends on compiled packages (pydantic_core, jiter), so fetch Linux
# wheels matching the Lambda runtime instead of the build machine's platform.
# Set LAMBDA_ARCH=aarch64 if the function runs on arm64.
LAMBDA_ARCH="${LAMBDA_ARCH:-x86_64}"
LAMBDA_PYTHON="${LAMBDA_PYTHON:-3.14}"
pip3 install -r <(grep -viE '^(boto3|botocore)([<>=!~ ]|$)' requirements.txt) -t package/ \
    --platform "manylinux2014_${LAMBDA_ARCH}" \
    --implementation cp \
    --python-version "${LAMBDA_PYTHON}" \
    --only-binary=:all:

# Strip bytecode caches to slim the package further. Keep *.dist-info: some
# deps (e.g. httpx2, used by anthropic) read their own package metadata at
# import time and fail with "No package metadata was found" without it.
find package -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null

# Copy Lambda function to package
cp lambda_function.py package/

# Create deployment zip
cd package
zip -r ../lambda_deployment.zip . -x '*.pyc'
cd ..

# Clean up
rm -rf package/

echo "Lambda deployment package created: lambda_deployment.zip"
echo "Upload this file to AWS Lambda console"