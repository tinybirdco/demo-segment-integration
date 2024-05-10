# Cloud Run Function for Segment Data Push

This repository contains a Python application that retrieves the latest enriched user event data from Tinybird and pushes it to Segment via their HTTP API. The function is packaged in a Docker container and deployed as a Google Cloud Run job.

**This repository is example code only and not intended for direct Production use.**

## Features

- **Data Retrieval**: Fetches user event data from Tinybird using REST APIs from last fetched timestamp
- **Batch Processing**: Efficiently pushes data to Segment in batches, with retry logic and chunking.
- **Logging & Monitoring**: Detailed logging for monitoring, troubleshooting, and status reporting.
- **Google Cloud Secrets**: Uses Google Cloud Secret Manager for secure configuration management.

## Requirements

- Python 3.9 or higher
- Docker (to build and run the container)
- Google Cloud SDK (for deployment)
- Tinybird and Segment credentials (stored in Google Cloud Secret Manager)

### Required Secrets and GCP Project ID

You are required to set an environment variable with the GCP Project ID, and the names of the required secrets to fetch from GCP Secret Manager.

- **GCP_PROJECT**: The ID of the Google Cloud project where Cloud Run and Secret Manager are configured.

- **Secrets** (stored in Google Cloud Secret Manager):
  - `TINYBIRD_TOKEN_SECRET`: The name of the Secret containing the Tinybird API authentication token.
  - `LAST_TS_SECRET`: The name of the Secret containing the Last processed timestamp, used to fetch new data since the last run. Starting from 0 is fine to fetch all rows, and then it will just fetch new rows once it catches up.
  - `SEGMENT_WRITE_KEY_SECRET`: The name of the Secret containing your Segment API write key for authentication.

### Optional Environment Variables

- `ROW_LIMIT`: The maximum number of rows to fetch from Tinybird (default: `5000`).
- `TINYBIRD_API_ROOT`: The base URL of the Tinybird API (default: `api.tinybird.co`).
- `TINYBIRD_API_ENDPOINT`: The Tinybird API endpoint to fetch data (default: `api_enriched_user_events_export`).
- `SEGMENT_API_ENDPOINT`: The Segment batch API endpoint (default: `https://api.segment.io/v1/batch`).
- `MAX_SEGMENT_BATCH_SIZE`: Maximum batch size to send to Segment (default: `500KB`).
- `MAX_SEGMENT_ROW_SIZE`: Maximum row size for an individual event (default: `32KB`).
- `SEGMENT_BATCH_SEND_DELAY`: Delay (in seconds) between batch sends (default: `1`).
- `SEGMENT_BATCH_SAMPLE_SIZE`: The number of events to sample when calculating the optimal chunk size for batches over 500KB (default: `50`).


## Setup and Deployment

1. **Clone the Repository**:
```bash
git clone <your-repo-url>
cd <repo-name>
```

You will likely want to modify the `main.py` code to match the schema of your data that you want to sync.

2. **Environment Configuration**:
    
    * Set up Google Cloud Secret Manager to securely store credentials as specified in requirements.
    * Add environment variables directly to Cloud Run or specify in the yaml template below.

3. **Build and Push Docker Image**:

```bash
docker build --platform linux/amd64 -t <gcp-artifact-repository-region>-docker.pkg.dev/<your-gcp-project-id>/<your-artifact-repository-name>/<your-image-name>:latest .
docker push <gcp-artifact-repository-region>-docker.pkg.dev/<your-gcp-project-id>/<your-artifact-repository-name>/<your-image-name>:latest
```

4. **Deploy to Google Cloud Run**:

Edit the default values in the sample `cloudRunJob.yaml` and use it to create your Job, or use the GUI.

```bash
gcloud run jobs create --file cloudRunJob.yaml
    --region <your-region>
```

5. **Create a schedule for syncing data**:
Edit the Cloud Schedule template and submit with the following command, or use the GUI.

```bash
gcloud scheduler jobs create http --file cloudScheduleTrigger.yaml
```