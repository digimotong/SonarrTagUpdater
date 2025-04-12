# Sonarr Tag Updater

Automatically updates show tags in Sonarr based on minimum episode scores and other criteria.

## Features

- **Score-based tagging** (uses minimum score across all episodes):
  - `negative_score` when any episode's customFormatScore < 0
  - `positive_score` when all episodes' customFormatScore > threshold (default: 100)
  - `no_score` when any episode has no score or scores between 0-threshold

- **Release group tagging**:
  - Adds `motong` tag when any episode's release group is "motong"

- **Resolution tagging**:
  - Adds `4k` tag when any episode's resolution is 2160p

## Requirements

- Python 3.6+
- Sonarr v3+
- API key with write permissions

## Installation

1. Clone this repository
2. Install requirements:
   ```bash
   pip install -r requirements.txt
   ```

3. Copy `config.example.json` to `config.json` and edit:
   ```json
   {
     "sonarr_url": "http://your-sonarr:8989",
     "sonarr_api_key": "your-api-key",
     "score_threshold": 100,
     "log_level": "INFO"
   }
   ```

## Usage

```bash
python sonarr_tag_updater.py [options]
```

Options:
- `--config`: Specify alternate config file (default: config.json)
- `--test`: Test mode (only processes first 5 shows)
- `--log-level`: Override log level (DEBUG, INFO, WARNING, ERROR)

## Automation

### Cron Job Setup

To run automatically on a schedule:

1. Find your Python path:
   ```bash
   which python3
   ```

2. Edit crontab:
   ```bash
   crontab -e
   ```

3. Add entries like:
   ```bash
   # Daily at 2am
   0 2 * * * /full/path/to/python3 /path/to/sonarr_tag_updater.py >> /path/to/sonarr_tag_updater.log 2>&1

   # Weekly on Sundays at 3am
   0 3 * * 0 /full/path/to/python3 /path/to/sonarr_tag_updater.py --log-level INFO >> /path/to/sonarr_tag_updater.log 2>&1
   ```

4. For log rotation, add to /etc/logrotate.d/:
   ```bash
   /path/to/sonarr_tag_updater.log {
       weekly
       rotate 4
       compress
       missingok
       notifempty
   }
   ```

## Tags

The script will automatically create these tags if missing:
- `negative_score` (red)
- `positive_score` (green) 
- `no_score` (gray)
- `motong` (purple)
- `4k` (blue)

## Logging

Detailed logs are written to `sonarr_tag_updater.log`

## Example Output

```
2025-04-10 09:30:00 - INFO - Starting Sonarr Tag Updater v1.0.0
2025-04-10 09:30:02 - DEBUG - Show: Band of Brothers - Min Score: -1200 - Tag: negative_score
2025-04-10 09:30:02 - DEBUG - Added motong tag for Adventure Time
2025-04-10 09:30:05 - INFO - Processing complete. Updated 42/100 shows
