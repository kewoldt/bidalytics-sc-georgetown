# Copyright (C) 2024 Kevin Ewoldt
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

import json
import anthropic
from anthropic import AnthropicBedrock
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import base64
import os
import logging
import time
from datetime import datetime, timedelta
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from pymongo import MongoClient

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def create_session_with_retries():
    """Create a requests session with retry strategy and proper headers"""
    session = requests.Session()
    
    # Define retry strategy with connection timeout retries
    retry_strategy = Retry(
        total=5,  # Increased total retries
        connect=3,  # Retry connection failures
        read=3,     # Retry read failures
        backoff_factor=2,  # Increased backoff
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS"]
    )
    
    # Mount adapter with retry strategy
    adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=10)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    # Set headers to mimic a real browser
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
    })
    
    return session

def get_first_monday_of_month(year, month):
    """Get the first Monday of a given month/year"""
    first_day = datetime(year, month, 1)
    # Find the first Monday (weekday 0 = Monday)
    days_ahead = 0 - first_day.weekday()
    if days_ahead <= 0:  # Target day already happened this week or is today
        days_ahead += 7
    return first_day + timedelta(days_ahead)

def is_federal_holiday(date):
    """Check if a date is a federal holiday that would move the auction"""
    year = date.year
    month = date.month
    day = date.day
    
    # New Year's Day (January 1)
    if month == 1 and day == 1:
        return True
    
    # July 4th (Independence Day)
    if month == 7 and day == 4:
        return True
    
    # Labor Day (first Monday in September)
    if month == 9:
        first_monday_sept = get_first_monday_of_month(year, 9)
        if date.date() == first_monday_sept.date():
            return True
    
    return False

def get_next_business_day(date):
    """Get the next business day (Monday-Friday)"""
    next_day = date + timedelta(days=1)
    # If it's Saturday (5) or Sunday (6), move to Monday
    while next_day.weekday() > 4:  # Monday=0, Friday=4
        next_day += timedelta(days=1)
    return next_day

def get_auction_date(year, month):
    """Get the auction date for a given month, accounting for federal holidays"""
    first_monday = get_first_monday_of_month(year, month)
    
    if is_federal_holiday(first_monday):
        # Move to the next business day
        auction_date = get_next_business_day(first_monday)
        logger.info(f"First Monday {first_monday.strftime('%Y-%m-%d')} is a federal holiday, moving to next business day: {auction_date.strftime('%Y-%m-%d')}")
    else:
        auction_date = first_monday
        logger.info(f"Auction date set to first Monday: {auction_date.strftime('%Y-%m-%d')}")
    
    return auction_date

def fetch_and_parse_webpage(session, main_url):
    """
    Fetch the county website and extract the PDF link for the most recent auction.
    
    Args:
        session: Configured requests session with retry logic
        main_url: URL of the county foreclosure page
        
    Returns:
        tuple: (pdf_url, month_label, calculated_auction_date)
            - Normal path: (str pdf_url, str month_label e.g. 'August 2026', datetime auction_date)
            - Skip path (most recent link is a strictly-past month):
              (None, str link_text, None) — pdf_url is None to signal the caller to skip.
        In both paths the 2nd element is a human-readable month/label string, so the
        caller can safely serialize it.

    Raises:
        Exception: If webpage cannot be fetched or parsed
    """
    logger.info(f"Step 1: Fetching main page: {main_url}")
    
    # Try multiple timeout strategies since websites don't like bots
    timeout_strategies = [
        (60, 90),   # (connect_timeout, read_timeout) - First try with longer timeouts
        (45, 60),   # Second try with medium timeouts
        (30, 45),   # Third try with shorter timeouts
    ]
    
    response = None
    last_error = None

    # fetch the html contents
    for attempt, (connect_timeout, read_timeout) in enumerate(timeout_strategies, 1):
        try:
            logger.info(f"Attempt {attempt}: Fetching with timeouts (connect={connect_timeout}s, read={read_timeout}s)")
            response = session.get(main_url, timeout=(connect_timeout, read_timeout))
            response.raise_for_status()
            logger.info(f"Successfully fetched main page on attempt {attempt}, status code: {response.status_code}, content length: {len(response.content)} bytes")
            break
        except requests.exceptions.Timeout as e:
            last_error = e
            logger.warning(f"Attempt {attempt} timeout: {str(e)}")
            if attempt < len(timeout_strategies):
                time.sleep(5)  # Wait before retry
            continue
        except requests.exceptions.ConnectionError as e:
            last_error = e
            logger.warning(f"Attempt {attempt} connection error: {str(e)}")
            if attempt < len(timeout_strategies):
                time.sleep(10)  # Longer wait for connection errors
            continue
    
    if response is None:
        logger.error(f"All attempts failed to fetch {main_url}. Last error: {str(last_error)}")
        raise Exception(f'Failed to fetch {main_url} after {len(timeout_strategies)} attempts. Last error: {str(last_error)}')
    
    # Step 2: Parse HTML and find first <a> tag after "Upcoming Foreclosure Sales" h2
    logger.info("Step 2: Parsing HTML to find PDF link")
    soup = BeautifulSoup(response.content, 'html.parser')
    
    # Find h2 with "Upcoming Foreclosure Sales" text
    h2_element = soup.find('h2', string=lambda text: text and 'Upcoming Foreclosure Sales' in text)
    if not h2_element:
        logger.error("Could not find h2 with 'Upcoming Foreclosure Sales' text")
        raise Exception('Could not find h2 with "Upcoming Foreclosure Sales" text')
    
    # Find the first <ul> element after this h2
    ul_element = h2_element.find_next_sibling('ul')
    if not ul_element:
        # Try finding ul as a descendant of next sibling
        next_sibling = h2_element.find_next_sibling()
        if next_sibling:
            ul_element = next_sibling.find('ul')
    
    if not ul_element:
        logger.error("Could not find ul element after 'Upcoming Foreclosure Sales' h2")
        raise Exception('Could not find ul element after "Upcoming Foreclosure Sales" h2')
    
    # Find first li element in the ul
    li_element = ul_element.find('li')
    if not li_element:
        logger.error("Could not find li element in foreclosure sales ul")
        raise Exception('Could not find li element in foreclosure sales ul')
    
    # Find first link in the li
    first_link = li_element.find('a')
    if not first_link or not first_link.get('href'):
        logger.error("Could not find first link in foreclosure sales li")
        raise Exception('Could not find first link in foreclosure sales li')
    
    # Check if this is a future month
    link_text = first_link.get_text(strip=True)
    logger.info(f"Found auction link text: '{link_text}'")
    
    try:
        # Parse the month/year from link text (e.g., "September 2025")
        auction_month_date = datetime.strptime(link_text, '%B %Y')
        current_date = datetime.now()
        current_month_start = datetime(current_date.year, current_date.month, 1)
        
        logger.info(f"Link month: {auction_month_date.strftime('%B %Y')}, Current month: {current_month_start.strftime('%B %Y')}")
        
        # Process the current month as well as future months: the current
        # month's sale is the first Monday, which is often still ahead when the
        # Lambda runs early in the month. Only strictly-past months are skipped.
        if auction_month_date < current_month_start:
            logger.info(f"Ending job. The most recent PDF link is a past month: '{link_text}', Current month: '{current_month_start.strftime('%B %Y')}'")
            return None, link_text, None  # Signal to skip processing
        
        # Update auction_date to use the calculated date for this month
        calculated_auction_date = get_auction_date(auction_month_date.year, auction_month_date.month)
        logger.info(f"Processing future auction for {link_text}, calculated auction date: {calculated_auction_date.strftime('%Y-%m-%d')}")
        
    except ValueError as e:
        logger.warning(f"Could not parse month/year from link text '{link_text}': {e}")
        logger.info("Proceeding with original logic")
        # Fallback to current month logic
        now = datetime.now()
        calculated_auction_date = get_auction_date(now.year, now.month)
        auction_month_date = now
        logger.info(f"Using fallback auction date: {calculated_auction_date.strftime('%Y-%m-%d')}")

    # Step 3: Construct PDF URL.
    # Resolve the (usually relative) href against the final URL of the page we
    # actually fetched (response.url follows any redirects). This keeps the PDF
    # link on the county's current domain even if COUNTY_URL points at an old one
    # that 301-redirects — hard-coding the domain here previously sent the PDF
    # download to a dead host and caused connect timeouts.
    pdf_href = first_link['href']
    pdf_url = urljoin(response.url, pdf_href)
    logger.info(f"Step 3: Constructed PDF URL: {pdf_url}")
    
    # Return the month label as a string (2nd element) so the contract is
    # consistent with the skip path; auction_month_date stays internal.
    return pdf_url, link_text, calculated_auction_date


def download_and_validate_pdf(session, pdf_url):
    """
    Download PDF file from URL and validate it's actually a PDF.
    
    Args:
        session: Configured requests session with retry logic
        pdf_url: URL of the PDF file to download
        
    Returns:
        bytes: PDF file content
        
    Raises:
        Exception: If download fails or file is not a PDF
    """
    logger.info(f"Step 4: Downloading file from: {pdf_url}")
    
    # PDF download timeout strategies (longer for file downloads)
    pdf_timeout_strategies = [
        (90, 120),  # (connect_timeout, read_timeout) - First try with longer timeouts
        (60, 90),   # Second try with medium timeouts
        (45, 60),   # Third try with shorter timeouts
    ]
    
    pdf_response = None
    last_pdf_error = None
    
    for attempt, (connect_timeout, read_timeout) in enumerate(pdf_timeout_strategies, 1):
        try:
            logger.info(f"PDF Download attempt {attempt}: Using timeouts (connect={connect_timeout}s, read={read_timeout}s)")
            pdf_response = session.get(pdf_url, timeout=(connect_timeout, read_timeout))
            pdf_response.raise_for_status()
            logger.info(f"Successfully downloaded file on attempt {attempt}, status code: {pdf_response.status_code}, size: {len(pdf_response.content)} bytes")
            break
        except requests.exceptions.Timeout as e:
            last_pdf_error = e
            logger.warning(f"PDF download attempt {attempt} timeout: {str(e)}")
            if attempt < len(pdf_timeout_strategies):
                time.sleep(10)  # Wait before retry
            continue
        except requests.exceptions.ConnectionError as e:
            last_pdf_error = e
            logger.warning(f"PDF download attempt {attempt} connection error: {str(e)}")
            if attempt < len(pdf_timeout_strategies):
                time.sleep(15)  # Longer wait for connection errors
            continue
    
    if pdf_response is None:
        logger.error(f"All PDF download attempts failed for {pdf_url}. Last error: {str(last_pdf_error)}")
        raise Exception(f'Failed to download PDF from {pdf_url} after {len(pdf_timeout_strategies)} attempts. Last error: {str(last_pdf_error)}')
    
    # Check file type by Content-Type header or URL extension
    content_type = pdf_response.headers.get('content-type', '').lower()
    file_extension = pdf_url.lower().split('.')[-1] if '.' in pdf_url else ''
    
    logger.info(f"File content-type: {content_type}, extension: {file_extension}")
    
    # Validate file type - only accept PDF
    is_pdf = (
        'application/pdf' in content_type or 
        file_extension == 'pdf' or
        pdf_response.content.startswith(b'%PDF')  # PDF magic number
    )
    
    if not is_pdf:
        logger.error(f"File type not supported. Expected PDF but received content-type: {content_type}, extension: {file_extension}")
        raise Exception(f"File type not supported - only PDF files are accepted. Content-type: {content_type}, extension: {file_extension}")
    
    logger.info("File validated as PDF format")
    return pdf_response.content


def strip_json_fence(text):
    """
    Remove a surrounding markdown code fence from model output and isolate the
    JSON payload.

    Claude sometimes returns the JSON wrapped like:
        ```json
        [ ... ]
        ```
    which is not valid JSON on its own. This strips the fence (with or without a
    language tag) and, as a fallback, trims to the outermost JSON array/object so
    any leading/trailing prose does not break json.loads().
    """
    cleaned = text.strip()

    if cleaned.startswith("```"):
        # Drop the opening fence line (e.g. "```json" or "```") and closing fence.
        lines = cleaned.split("\n")
        lines = lines[1:]  # remove opening ``` line
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    # Fallback: isolate the outermost array or object if any stray text remains.
    start = min(
        (i for i in (cleaned.find("["), cleaned.find("{")) if i != -1),
        default=-1,
    )
    if start != -1:
        end = max(cleaned.rfind("]"), cleaned.rfind("}"))
        if end > start:
            cleaned = cleaned[start:end + 1]

    return cleaned


def process_pdf_with_bedrock(pdf_content, auction_date):
    """
    Process PDF content with AWS Bedrock to extract foreclosure data.
    
    Args:
        pdf_content: Raw PDF file content as bytes
        auction_date: Calculated auction date for the records
        
    Returns:
        list: Parsed foreclosure records as list of dictionaries
        
    Raises:
        Exception: If Bedrock processing fails or returns invalid JSON
    """
    # Step 5: Encode PDF to base64 for Bedrock
    logger.info("Step 5: Encoding PDF to base64")
    pdf_base64 = base64.b64encode(pdf_content).decode('utf-8')
    logger.info(f"PDF encoded to base64, length: {len(pdf_base64)} characters")
    
    # Step 6: Prepare Bedrock request with foreclosure parsing prompt
    logger.info("Step 6: Preparing Bedrock request")
    # bedrock-runtime InvokeModel via the anthropic SDK. Region and credentials
    # come from the Lambda environment (AWS_REGION + execution role). Current
    # Claude models are only reachable here through inference-profile IDs
    # (e.g. us./global.anthropic.claude-...), not on the bedrock-mantle endpoint.
    bedrock = AnthropicBedrock()

    prompt = f"""You are a parser that extracts structured rows from a tabular foreclosure PDF.
Rules:
- Read the PDF and find the main table of sales.
- Skip the first row of column headers.
- For each remaining row, map the first five cell values, by index, to JSON attributes:
  0 = caseNumber
  1 = plaintiff
  2 = defendant
  3 = tms
  4 = address
- Special rules for the address column:
  * If the value contains a comma, split on the LAST comma.
    - Everything before the comma is `address`.
    - Everything after the comma is `city` (trim it).
  * If the city is 'Gtown', output 'Georgetown' instead.
  * If no comma exists, output the entire cell as `address` and set the value of `city` to 'Georgetown'.
- Return ONLY valid JSON: an array of objects like
  [{{"caseNumber", "plaintiff", "defendant", "tms", "address", "county", "city", "auctionDate", "state"}}, ...]
- For the `county` attribute always set it to 'Georgetown'.
- For the `state` attribute always set it to 'SC'.
- For the `auctionDate` attribute always set the value to '{auction_date}'.
- Do NOT include any explanations or markdown—JSON only."""

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": pdf_base64
                    }
                },
                {
                    "type": "text",
                    "text": prompt
                }
            ]
        }
    ]

    # Step 7: Call Bedrock API
    # MODEL_ID is required and configured in the Lambda console (kept out of
    # source so the model choice isn't published in this public repo).
    model_id = os.environ.get('MODEL_ID')
    if not model_id:
        raise ValueError("MODEL_ID environment variable is required (Bedrock inference-profile ID, e.g. us.anthropic.claude-...)")
    logger.info(f"Step 7: Calling Bedrock API with model: {model_id}")
    response = bedrock.messages.create(
        model=model_id,
        max_tokens=16000,
        # Table extraction doesn't need deep reasoning; low effort keeps
        # thinking (on by default for current models) cheap and fast.
        output_config={"effort": "low"},
        messages=messages,
    )
    logger.info(f"Bedrock API call successful, stop_reason: {response.stop_reason}")

    # Step 8: Parse response
    logger.info("Step 8: Parsing Bedrock response")
    if response.stop_reason == "refusal":
        raise Exception(f"Bedrock model declined the request: {response.stop_details}")
    if response.stop_reason == "max_tokens":
        logger.warning("Bedrock response hit max_tokens; output may be truncated")
    # The response can start with a thinking block, so pick the text block by type.
    parsed_data = next((block.text for block in response.content if block.type == "text"), "")
    logger.info(f"Received response from Bedrock, length: {len(parsed_data)} characters")

    # Current models don't support assistant prefill, so strip any markdown
    # fence and isolate the JSON array/object before parsing.
    parsed_data = strip_json_fence(parsed_data)

    try:
        foreclosure_records = json.loads(parsed_data)
        logger.info(f"Successfully parsed JSON, found {len(foreclosure_records)} foreclosure records")
        return foreclosure_records
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Bedrock response as JSON: {str(e)}")
        logger.error(f"Raw response: {parsed_data}")
        raise Exception(f"Failed to parse Bedrock response as JSON: {str(e)}")


def save_records_to_mongodb(foreclosure_records, auction_date):
    """
    Save or update foreclosure records in MongoDB.
    
    Args:
        foreclosure_records: List of foreclosure record dictionaries
        auction_date: Calculated auction date for the records
        
    Returns:
        tuple: (updated_count, created_count)
        
    Raises:
        Exception: If MongoDB operations fail
    """
    logger.info("Step 9: Parsing JSON and saving to MongoDB")
    updated_count = 0
    created_count = 0
    
    # Connect to MongoDB
    mongo_url = os.environ.get('MONGO_DB_URL')
    if not mongo_url:
        logger.error("MONGO_DB_URL environment variable not set")
        raise Exception('MONGO_DB_URL environment variable not set')
    
    client = None
    try:
        logger.info("Connecting to MongoDB")
        client = MongoClient(
            mongo_url, 
            tls=True, 
            tlsAllowInvalidCertificates=True,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            socketTimeoutMS=5000
        )
        db = client.get_default_database()
        collection = db.auctionitems
        logger.info("Successfully connected to MongoDB")
        
        # Fetch existing items for SC Georgetown
        logger.info("Fetching existing items from MongoDB for SC Georgetown")
        existing_items = list(collection.find({'state': 'SC', 'county': 'Georgetown'}))
        logger.info(f"Found {len(existing_items)} existing items in MongoDB")
        
        # Process each record
        logger.info(f"Processing {len(foreclosure_records)} records")
        for i, record in enumerate(foreclosure_records):
            case_number = record.get('caseNumber', 'Unknown')
            logger.info(f"Processing record {i+1}/{len(foreclosure_records)}: Case #{case_number}")
            
            # Set the calculated auction date
            record['auctionDate'] = auction_date
            
            # Find existing item by caseNumber
            existing_item = next((item for item in existing_items if item.get('caseNumber') == record.get('caseNumber')), None)
            
            if existing_item:
                # Update existing record
                logger.info(f"Updating existing record for case #{case_number}")
                update_data = {
                    'auctionDate': auction_date,
                    'active': record.get('active', True),
                    'updateDate': datetime.now()
                }
                
                collection.update_one(
                    {'_id': existing_item['_id']},
                    {'$set': update_data}
                )
                updated_count += 1
                logger.info(f"Successfully updated case #{case_number}")
            else:
                # Create new record
                logger.info(f"Creating new record for case #{case_number}")
                record['auctionDate'] = auction_date
                record['active'] = record.get('active', True)
                record['isReopen'] = False
                record['attemptedRentCastValueApi'] = False
                record['attemptedRentCastPropertiesApi'] = False
                record['attemptedRentCastRentApi'] = False
                record['attemptedGeoCodeApi'] = False
                record['createDate'] = datetime.now()
                
                collection.insert_one(record)
                created_count += 1
                logger.info(f"Successfully created case #{case_number}")
    
    finally:
        if client:
            client.close()
        logger.info(f"MongoDB operations complete. Updated: {updated_count}, Created: {created_count}")
    
    return updated_count, created_count


def lambda_handler(event, context):
    """
    AWS Lambda function that fetches foreclosure data and processes with Bedrock.
    Orchestrates the entire workflow through smaller, focused functions.
    
    Args:
        event: Lambda event object
        context: Lambda context object
        
    Returns:
        dict: API response with status code and result body
    """
    
    try:
        logger.info("Starting foreclosure processing")

        # Validate required configuration up front so we fail fast before doing
        # any network work. These are set in the Lambda console, not in source.
        if not os.environ.get('MODEL_ID'):
            raise ValueError("MODEL_ID environment variable is required (Bedrock model / inference-profile ARN)")
        main_url = os.environ.get('COUNTY_URL')
        if not main_url:
            raise ValueError("COUNTY_URL environment variable is required")

        # Create session with retry logic and proper headers
        session = create_session_with_retries()
        
        # Step 1-3: Fetch and parse webpage to get PDF URL
        pdf_url, auction_month_info, auction_date = fetch_and_parse_webpage(session, main_url)
        
        # Check if we should skip processing (most recent link is a strictly-past month)
        if pdf_url is None:
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': f'Skipped processing {auction_month_info} - showing only upcoming auctions',
                    'auction_month': auction_month_info,
                    'records_processed': 0
                })
            }
        
        # Step 4: Download and validate PDF file
        pdf_content = download_and_validate_pdf(session, pdf_url)
        
        # Step 5-8: Process PDF with Bedrock AI
        foreclosure_records = process_pdf_with_bedrock(pdf_content, auction_date)
        
        # Step 9: Save records to MongoDB
        updated_count, created_count = save_records_to_mongodb(foreclosure_records, auction_date)
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'pdf_url': pdf_url,
                'auction_date': auction_date.isoformat(),
                'records_updated': updated_count,
                'records_created': created_count,
                'total_processed': len(foreclosure_records)
            })
        }
        
    except requests.RequestException as e:
        logger.error(f"HTTP request error: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': f'HTTP request error: {str(e)}'
            })
        }
    except anthropic.APIError as e:
        logger.error(f"AWS Bedrock error: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': f'AWS Bedrock error: {str(e)}'
            })
        }
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': f'Unexpected error: {str(e)}'
            })
        }