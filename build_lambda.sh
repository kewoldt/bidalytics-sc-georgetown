#!/bin/bash

# Build script for AWS Lambda deployment package

echo "Building Lambda deployment package..."

# Clean up previous builds
rm -rf package/
rm -f lambda_deployment.zip

# Create package directory
mkdir package

# Install dependencies to package directory
pip3 install -r requirements.txt -t package/

# Copy Lambda function to package
cp lambda_function.py package/

# Create deployment zip
cd package
zip -r ../lambda_deployment.zip .
cd ..

# Clean up
rm -rf package/

echo "Lambda deployment package created: lambda_deployment.zip"
echo "Upload this file to AWS Lambda console"