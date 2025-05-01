# Sonarr Tag Updater

Automatically updates show tags in Sonarr based on custom format scores, release groups, and quality information.

## Features

- **Score-based tagging**:
  - Uses the LOWEST score found across all episode files
  - `negative_score` (red) when customFormatScore < 0
  - `positive_score` (green) when customFormatScore > threshold (default: 100)
  - `no_score` (gray) when score is None or between 0-threshold

- **Quality tagging**:
  - `4k` (blue) when ANY episode file has 2160p resolution (configurable via TAG_4K env var)
 
- **Release group tagging**:
  - `motong` (purple) when ANY episode file has release group "motong" (configurable via TAG_MOTONG env var)

## Containerized Deployment

The application is designed to run in Docker with Sonarr. Here's a sample compose configuration:

```yaml
services:
  sonarr-tagger:
    image: digimotong/sonarr-tagger:latest
    container_name: sonarr-tagger
    restart: unless-stopped
    depends_on:
      - sonarr
    environment:
      SONARR_URL: http://sonarr:8989  # Sonarr instance URL
      SONARR_API_KEY: your-api-key    # Sonarr API key (required)
      LOG_LEVEL: INFO                 # DEBUG, INFO, WARNING, ERROR
      SCORE_THRESHOLD: 100            # Threshold for positive_score
      INTERVAL_MINUTES: 20            # Minutes between runs
      # TAG_4K: true                  # Enable 4k tagging
      # TAG_MOTONG: true              # Enable motong tagging
```

### Required Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `SONARR_URL` | Sonarr instance URL | `http://sonarr:8989` |
| `SONARR_API_KEY` | Sonarr API key with write permissions | `your-api-key` |

### Optional Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Logging verbosity (DEBUG, INFO, WARNING, ERROR) |
| `SCORE_THRESHOLD` | `100` | Score threshold for positive_score tag |
| `INTERVAL_MINUTES` | `20` | Minutes between automatic runs |
| `TAG_4K` | `false` | Enable 4k resolution tagging |
| `TAG_MOTONG` | `false` | Enable motong release group tagging |

## Tag Management

The application automatically creates and manages these tags:

| Tag Name | Color | Trigger Condition |
|----------|-------|-------------------|
| negative_score | #ff0000 | LOWEST episode score < 0 |
| positive_score | #00ff00 | LOWEST episode score > threshold |
| no_score | #808080 | No score or 0 ≤ score ≤ threshold |
| 4k | #0000ff | ANY episode file is 2160p (requires TAG_4K=true) |
| motong | #800080 | ANY episode file contains "motong" (requires TAG_MOTONG=true) |

Tags are created automatically if they don't exist in Sonarr.

## Monitoring

View container logs to monitor operation:

```bash
docker logs sonarr-tagger
```

Example log output:
```
2025-04-27 12:00:00 - INFO - Starting Sonarr Tag Updater v1.0.0
2025-04-27 12:00:02 - INFO - Processing 125 shows
2025-04-27 12:00:05 - DEBUG - Show: Breaking Bad - Score: 150 - Tag: positive_score
2025-04-27 12:00:05 - DEBUG - Added 4k tag for Breaking Bad
2025-04-27 12:00:10 - INFO - Processing complete. Updated 18/125 shows
2025-04-27 12:00:10 - INFO - Next run in 20 minutes
```

## Requirements

- Docker
- Sonarr v3+
- API key with write permissions
- Network access to Sonarr instance
