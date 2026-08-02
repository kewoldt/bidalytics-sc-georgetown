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
pip3 install -r <(grep -viE '^(boto3|botocore)([<>=!~ ]|$)' requirements.txt) -t package/

# Strip bytecode caches and dist metadata to slim the package further
find package -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null
find package -type d -name '*.dist-info' -exec rm -rf {} + 2>/dev/null
find package -type d -name '*.egg-info' -exec rm -rf {} + 2>/dev/null

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