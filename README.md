# Georgetown County, SC,  Foreclosure Processing Lambda

An AWS Lambda function that automatically processes Georgetown County foreclosure auction data using AWS Bedrock AI and stores results in MongoDB.

## Overview

This Lambda function:
1. Fetches the Georgetown County foreclosure sales webpage
2. Extracts the PDF link for the most recent auction month (current or future)
3. Downloads and validates PDF files (rejects non-PDF formats like XLS)
4. Uses AWS Bedrock (Claude Sonnet) to parse foreclosure data from PDFs
5. Calculates proper auction dates with federal holiday handling
6. Saves/updates records in MongoDB with duplicate prevention

## Features

- **Smart Month Filtering**: Processes the current and future auction months, skips strictly-past months
- **File Type Validation**: Rejects non-PDF files (XLS, etc.) with clear error messages
- **Federal Holiday Handling**: Automatically adjusts auction dates when first Monday conflicts with holidays
- **MongoDB Integration**: Saves structured data with duplicate prevention by case number
- **Comprehensive Logging**: Detailed CloudWatch logs for debugging and monitoring
- **Unit Testing**: 25 test cases covering date calculations, webpage parsing, PDF-URL construction, and file validation

## Architecture

```
Georgetown County Website → Lambda Function → AWS Bedrock → MongoDB
                                    ↓
                           CloudWatch Logs
```

## Requirements

### AWS Services
- **AWS Lambda**: Python 3.14 runtime
- **AWS Bedrock**: Claude Sonnet 4.5 model access
- **IAM Role**: With permissions for Bedrock and CloudWatch Logs
- **VPC/NAT Gateway**: For static IP if MongoDB requires IP whitelisting

### External Services
- **MongoDB Atlas**: Database for storing foreclosure records
- **Internet Access**: To fetch Georgetown County website content

## Setup Instructions

### 1. Clone and Build

```bash
git clone <repository-url>
cd bidalytics-sc-georgetown

# Install dependencies locally for testing (optional)
pip3 install -r requirements.txt

# Build deployment package
chmod +x build_lambda.sh
./build_lambda.sh
```

### 2. Environment Variables

Set these in AWS Lambda Configuration:

| Variable | Description | Example |
|----------|-------------|---------|
| `MONGO_DB_URL` | MongoDB connection string | `mongodb+srv://user:pass@cluster.mongodb.net/dbname` |
| `MODEL_ID` | Bedrock model ARN (Claude Sonnet 4.5) | `arn:aws:bedrock:us-east-1::inference-profile/us.anthropic.claude-sonnet-4-5-20250929-v1:0` |
| `COUNTY_URL` | County foreclosure page URL | |

### 3. IAM Permissions

Lambda execution role needs:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "bedrock:InvokeModel"
            ],
            "Resource": "arn:aws:bedrock:*:*:inference-profile/*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents"
            ],
            "Resource": "arn:aws:logs:*:*:*"
        }
    ]
}
```

### 4. Deploy to AWS Lambda

1. Upload `lambda_deployment.zip` to AWS Lambda Console
2. Set handler to `lambda_function.lambda_handler`
3. Configure environment variables
4. Set timeout to 5+ minutes (PDF processing can take time)
5. Assign IAM role with proper permissions

### 5. MongoDB Setup

Ensure MongoDB Atlas:
- Has IP whitelist configured for Lambda's egress IPs
- Database and `auctionitems` collection exist
- Connection string includes proper credentials

## Data Schema

Foreclosure records saved to MongoDB:

```javascript
{
  "_id": ObjectId,
  "caseNumber": "2023CP-1234",
  "plaintiff": "Bank Name",
  "defendant": "Property Owner",
  "tms": "123-45-67-890",
  "address": "123 Main St",
  "city": "Georgetown", 
  "county": "Georgetown",
  "state": "SC",
  "auctionDate": ISODate("2025-03-03T00:00:00Z"),
  "active": true,
  "isReopen": false,
  "attemptedZillowApi": false,
  "attemptedRentCastApi": false,
  "attemptedGeoCodeApi": false,
  "createDate": ISODate("2025-01-15T10:30:00Z"),
  "updateDate": ISODate("2025-01-15T10:30:00Z")
}
```

## Testing

Run unit tests locally:

```bash
# Install test dependencies
pip3 install pytest pytest-mock

# Run all tests
python3 -m unittest test_lambda.py -v

# Run specific test suites
python3 -m unittest test_lambda.TestDateMethods -v
python3 -m unittest test_lambda.TestFileTypeValidation -v
python3 -m unittest test_lambda.TestHTMLParsing -v
python3 -m unittest test_lambda.TestMonthFiltering -v
python3 -m unittest test_lambda.TestFetchAndParseWebpage -v
```

## Scheduling

Set up EventBridge (CloudWatch Events) to trigger Lambda:
- **Frequency**: Weekly or monthly
- **Target**: Georgetown County updates their foreclosure PDFs regularly

Example EventBridge (CloudWatch Events) rule:
```json
{
  "ScheduleExpression": "cron(30 10 ? * WED *)",
  "Description": "Run Georgetown foreclosure processing every Wednesday at 10:30 UTC"
}
```

## Error Handling

Common error scenarios:

| Error | Cause | Solution |
|-------|-------|----------|
| MongoDB SSL handshake failed | IP not whitelisted | Add Lambda egress IPs to MongoDB Atlas |
| Bedrock access denied | Missing permissions | Update IAM role |
| File type not supported | XLS file instead of PDF | Check Georgetown County website format |
| Could not find "Upcoming Foreclosure Sales" h2 / ul / li / link | Website structure changed | Update the selector chain in `fetch_and_parse_webpage()` |
| Failed to fetch ... after N attempts (connect timeout) | `COUNTY_URL` points at an unreachable/old domain | Point `COUNTY_URL` at the county's current domain |

## Monitoring

Key CloudWatch metrics to monitor:
- **Function Duration**: Should complete within timeout
- **Error Rate**: Monitor for parsing failures
- **Memory Usage**: Adjust if needed for large PDFs

Log messages include:
- PDF download success/failure
- File type validation results
- Bedrock API response status
- MongoDB operation results
- Record counts (created/updated)

## Development

### File Structure
```
bidalytics-sc-georgetown/
├── lambda_function.py      # Main Lambda handler
├── test_lambda.py         # Unit tests
├── requirements.txt       # Python dependencies  
├── build_lambda.sh       # Deployment script
├── README.md             # This file
└── lambda_deployment.zip # Generated deployment package
```

### Key Functions
- `get_auction_date(year, month)`: Calculates auction date with holiday handling
- `is_federal_holiday(date)`: Checks for New Year's, July 4th, Labor Day
- `lambda_handler(event, context)`: Main entry point

## Troubleshooting

1. **Check CloudWatch Logs** for detailed error messages
2. **Verify Environment Variables** are set correctly
3. **Test MongoDB Connection** separately if database errors occur
4. **Confirm Bedrock Model Access** in your AWS region
5. **Check Georgetown County Website** for structure changes

## License

MIT License - See LICENSE file for details