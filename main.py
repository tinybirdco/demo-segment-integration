import logging
import os
import base64
import json
import datetime
from time import sleep
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

from google.cloud import secretmanager

# Configure logging
logging.basicConfig(level=logging.INFO)

# Control Values
project_id = os.environ['GCP_PROJECT']
if not project_id:
    raise ValueError("Environment variable 'GCP_PROJECT' not set.")

row_limit = os.environ.get('ROW_LIMIT', 5000)
tinybird_api_root = os.environ.get('TINYBIRD_API_ROOT', 'api.tinybird.co')
tinybird_api_endpoint = os.environ.get('TINYBIRD_API_ENDPOINT', 'api_enriched_user_events_export')
segment_api_endpoint = os.environ.get('SEGMENT_API_ENDPOINT', 'https://api.segment.io/v1/batch')
max_segment_batch_size = os.environ.get('MAX_SEGMENT_BATCH_SIZE', 500 * 1024)  # 500KB
max_segment_row_size = os.environ.get('MAX_SEGMENT_ROW_SIZE', 32 * 1024)  # 32KB
segment_batch_send_delay = os.environ.get('SEGMENT_BATCH_SEND_DELAY', 1)  # 1 seconds
segment_batch_sample_size = os.environ.get('SEGMENT_BATCH_SAMPLE_SIZE', 50)  # 50 events

# Names of Secrets to fetch from Secret Manager
tinybird_token_secret = os.environ.get('TINYBIRD_TOKEN_SECRET', 'demo-segment-tinybird-token')
last_ts_secret = os.environ.get('LAST_TS_SECRET', 'demo-segment-last-ts')
segment_write_key_secret = os.environ.get('SEGMENT_WRITE_KEY_SECRET', 'demo-segment-write-key')

# Setup retries with exponential backoff
def setup_requests_session():
    session = requests.Session()
    retry_strategy = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount('https://', adapter)
    return session

# Function to access secrets from Secret Manager with validity check
def get_secret(secret_name):
    secret_path = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
    try:
        logging.info(f"Fetching secret {secret_path}...")
        response = secret_client.access_secret_version(request={"name": secret_path})
        resp = response.payload.data.decode('UTF-8')
        if resp and resp == "<default_value>":
            raise ValueError(f"Secret {secret_path} is using a default value.")
        if resp and resp == "":
            raise ValueError(f"Secret {secret_path} is an Empty String")
        else:
            return resp
    except Exception as e:
        logging.error(f"Error fetching secret {secret_path}: {e}")
        raise

# Function to set secret in Secret Manager
def set_secret(secret_name, secret_value):
    secret_path = f"projects/{project_id}/secrets/{secret_name}"
    logging.info(f"Setting secret {secret_path}...")
    secret_client.add_secret_version(
        request={
            "parent": secret_path,
            "payload": {"data": str(secret_value).encode('UTF-8')}
        }
    )

# Function to calculate chunk size using a sample of up to 50 events
def calculate_optimal_chunk_size(events, sample_size=segment_batch_sample_size):
    # Use all events if the total count is less than the sample size
    sample_events = events[:min(sample_size, len(events))]
    
    # Calculate the average event size based on the sample
    total_size = sum(len(json.dumps(event)) for event in sample_events)
    avg_event_size = total_size // len(sample_events) if sample_events else 1

    # Calculate the optimal chunk size that maximizes the 500 KB limit
    chunk_size = max_segment_batch_size // avg_event_size
    return max(1, chunk_size)

# Function to send batch to Segment
def send_batch_to_segment(batch):
    segment_write_key = get_secret(segment_write_key_secret)
    encoded_segment_key = base64.b64encode(f"{segment_write_key}:".encode('utf-8')).decode('utf-8')
    segment_headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Basic {encoded_segment_key}'
    }
    segment_response = session.post(segment_api_endpoint, headers=segment_headers, data=json.dumps({'batch': batch}))
    if segment_response.status_code != 200:
        raise ValueError(f"Error sending to Segment: {segment_response.status_code} Details: {segment_response.text}")
    # Log Segment response for debugging
    logging.info(f"Segment Response: {segment_response.text}")

# Function to send batches in dynamically calculated chunks
def send_batches_in_chunks(batch):
    chunk_size = calculate_optimal_chunk_size(batch)

    for i in range(0, len(batch), chunk_size):
        chunk = batch[i:i + chunk_size]

        logging.info(f"Sending chunk {i // chunk_size + 1} of {len(batch) // chunk_size + 1}...")
        send_batch_to_segment(chunk)
        sleep(segment_batch_send_delay)

# Function to fetch data from Tinybird
def fetch_data_from_tinybird():
    tinybird_token = get_secret(tinybird_token_secret)
    last_ts = get_secret(last_ts_secret)
    params = {
        'last_ts': last_ts,
        'row_limit': row_limit,
        'token': tinybird_token
    }
    tinybird_url = f'https://{tinybird_api_root}/v0/pipes/{tinybird_api_endpoint}.json'
    try:
        response = session.get(tinybird_url, params=params)
        if response.status_code != 200:
            error_message = response.json().get('error', 'Unknown error')
            raise ValueError(f"Error fetching data from Tinybird: {response.status_code} - {error_message}")

        # Parse JSON response
        data = response.json()
        if 'data' not in data:
            raise ValueError(f"Unexpected response format from Tinybird API: {data}")
        logging.info(f"Received {len(data['data'])} rows from Tinybird.")
        return data['data']

    except requests.exceptions.RequestException as e:
        logging.exception(f"Request error while connecting to Tinybird API: {e}")
        raise

# Function to prepare Tinybird data into Segment Tracking format
def prepare_segment_tracking_data(data, userId='user_id', event='event', timestamp='timestamp'):
    batch = []
    for row in data:
        # Check Row is not over max row size or log and skip row
        if len(json.dumps(row)) > max_segment_row_size:
            logging.error(f"Row too large, skipping: {len(json.dumps(row))} bytes")
            continue
        
        batch.append({
            'type': 'track',
            'userId': row[userId],
            'event': row[event],
            'properties': row,
            'timestamp': datetime.datetime.fromtimestamp(row[timestamp]).isoformat()
        })
    return batch

# Clients
session = setup_requests_session()
secret_client = secretmanager.SecretManagerServiceClient()

# Main Process
# Fetch data from Tinybird
logging.info(f"Starting Run at {datetime.datetime.now()}")
logging.info("Fetching data from Tinybird...")
data = fetch_data_from_tinybird()

# Process data if found
if not data:
    logging.info("No new data found.")
    exit()
else:
    #Prepare batch array of events to send to Segment
    batch = prepare_segment_tracking_data(data)

    # Send in chunks of over max batch size, else send single batch
    if len(json.dumps(batch)) > max_segment_batch_size:
        logging.info("Batch too large, sending in chunks...")
        send_batches_in_chunks(batch)
    else:
        logging.info("Sending single batch...")
        send_batch_to_segment(batch)

    # Update the last_ts value for the next batch
    logging.info("Updating last_ts...")
    next_last_ts = max(row['timestamp'] for row in data)
    set_secret(last_ts_secret, next_last_ts)

logging.info(f"Run Complete at {datetime.datetime.now()}")