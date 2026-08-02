# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install runtime deps
pip3 install -r requirements.txt

# Install dev/test deps
pip3 install -r requirements-dev.txt

# Run all tests
python3 -m unittest test_lambda.py -v

# Run a specific test class
python3 -m unittest test_lambda.TestDateMethods -v
python3 -m unittest test_lambda.TestFileTypeValidation -v
python3 -m unittest test_lambda.TestHTMLParsing -v
python3 -m unittest test_lambda.TestMonthFiltering -v

# Build Lambda deployment zip
./build_lambda.sh
```

## Architecture

Single-file Lambda (`lambda_function.py`) with a linear pipeline:

```
Georgetown County website → fetch_and_parse_webpage()
  → download_and_validate_pdf()
  → process_pdf_with_bedrock()   ← Claude via Bedrock extracts rows as JSON
  → save_records_to_mongodb()    ← upserts to auctionitems collection
```

**Key behaviors:**
- Processes the **current and future** auction months — only if the most recent PDF link is a strictly-past month does the Lambda exit early with a 200. (The current month's sale is the first Monday, which is often still ahead when the Lambda runs early in the month.)
- Auction date = first Monday of the month, bumped to next business day if it falls on New Year's Day, July 4th, or Labor Day.
- `is_federal_holiday()` only covers three holidays — extend it there if more are needed.
- MongoDB upsert key is `caseNumber`. New records get flags set (`attemptedGeoCodeApi`, `attemptedRentCastApi`, etc.) that the main bidalytics-service picks up for enrichment.
- `tlsAllowInvalidCertificates=True` is intentional for MongoDB Atlas compatibility.

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `MONGO_DB_URL` | MongoDB Atlas connection string |
| `MODEL_ID` | **Required** — Bedrock model / inference-profile ARN (set in Lambda console; no default in source) |
| `COUNTY_URL` | Georgetown County foreclosure page URL |

## Deployment

- Runtime: Python 3.14 (set in Lambda console)
- Trigger: EventBridge cron `30 10 ? * WED *` (10:30 UTC every Wednesday)
- Handler: `lambda_function.lambda_handler`
- Timeout: 5+ minutes recommended
- Build: `./build_lambda.sh` → upload `lambda_deployment.zip` to Lambda console

IAM role needs `bedrock:InvokeModel` on the inference profile ARN and standard CloudWatch Logs permissions.

## HTML Parsing Fragility

`fetch_and_parse_webpage()` finds the PDF link by locating an `<h2>` containing "Upcoming Foreclosure Sales", then the next `<ul>` sibling, then the first `<li><a>`. If the county website restructures this section, parsing will break — check the selector chain first when debugging fetch failures.
