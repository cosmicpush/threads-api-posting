# Threads Image Poster

Automates Threads posts by selecting a random PNG from an OCI Object Storage bucket, uploading it through the official Threads Graph API, and deleting the image from the bucket after a successful post.

## Prerequisites
- Python 3.10+
- OCI credentials (via `~/.oci/config`) with access to `THREADS_BUCKET`
- Threads Graph API access token with publish permissions
- Claude API key with access to the latest vision-capable model (default: `claude-3-5-sonnet-20241022`)

## Setup
1. Install dependencies:
   ```bash
   python -m venv .venv
   . .venv/bin/activate
   pip install -r requirements.txt
   ```
2. Copy the sample environment file and fill in your values:
   ```bash
   cp .env.example .env
   ```
3. Ensure your OCI profile can list objects, create pre-authenticated requests, and delete objects in the target bucket.
4. Provide your Anthropic Claude API key in the environment so captions can be generated automatically.

## Usage
Run the poster manually:
```bash
python -m threads_poster
```
The script:
1. Loads configuration and credentials from the environment
2. Lists all PNG files in the configured OCI bucket/prefix
3. Picks a random image and creates a pre-authenticated URL
4. Sends the image to Claude Vision to craft a one-line caption that reflects the quote
5. Creates and publishes the Threads post with the generated caption
6. Deletes the posted image from OCI once the upload succeeds

Logs are printed to stdout with timestamps to simplify automation and alerting.

## Scheduling
`cron/threads_poster.cron` contains a ready-to-import crontab entry that runs the script every hour from 09:30 to 21:30 IST (04:00-16:00 UTC):
```bash
crontab cron/threads_poster.cron
```
Adjust the repository path or Python interpreter in that file to match your environment before loading it.

## Environment Variables
The following variables are required (see `.env.example`):
- `THREADS_ACCESS_TOKEN`
- `THREADS_USER_ID`
- `THREADS_BUCKET`
- `OCI_NAMESPACE`
- `OCI_REGION` (falls back to the region in `~/.oci/config` if omitted)
- `ANTHROPIC_API_KEY` (required when `THREADS_ENABLE_CAPTIONING` is `true`)

Optional variables:
- `THREADS_PREFIX` to limit selection to a subfolder
- `THREADS_ENABLE_CAPTIONING` to toggle Claude caption generation (set to `false` for silent posts)
- `OCI_PROFILE` to select a non-default profile from `~/.oci/config`
- `THREADS_CLAUDE_MODEL` to target a different Claude vision model
- `THREADS_CLAUDE_MAX_TOKENS` to adjust the caption response limit
- `THREADS_CAPTION_FALLBACK` to set fallback text if the Claude request fails
- `THREADS_MEDIA_WAIT_SECONDS` to adjust the media processing wait
- `THREADS_PRESIGN_EXPIRATION_SECONDS` to tweak presigned URL validity
