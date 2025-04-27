#!/usr/bin/env python3
"""
Sonarr Tag Updater
Fetches shows from Sonarr API and updates tags based on episode scores.
"""

import os
import sys
import argparse
import logging
import time
from typing import Dict, List
import requests
from requests.exceptions import RequestException

class SonarrAPI:
    """Client for Sonarr API interactions"""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            'X-Api-Key': self.api_key,
            'Accept': 'application/json'
        })

    def get_shows(self) -> List[Dict]:
        """Fetch all shows from Sonarr"""
        endpoint = f"{self.base_url}/api/v3/series"
        try:
            response = self.session.get(endpoint)
            response.raise_for_status()
            return response.json()
        except RequestException as e:
            logging.error("Failed to fetch shows: %s", str(e))
            raise

    def get_tags(self) -> List[Dict]:
        """Fetch all tags from Sonarr"""
        endpoint = f"{self.base_url}/api/v3/tag"
        try:
            response = self.session.get(endpoint)
            response.raise_for_status()
            return response.json()
        except RequestException as e:
            logging.error("Failed to fetch tags: %s", str(e))
            raise

    def create_tag(self, label: str, color: str = "#808080") -> Dict:
        """Create a new tag in Sonarr"""
        endpoint = f"{self.base_url}/api/v3/tag"
        try:
            response = self.session.post(endpoint, json={
                'label': label,
                'color': color
            })
            response.raise_for_status()
            return response.json()
        except RequestException as e:
            logging.error("Failed to create tag '%s': %s", label, str(e))
            raise

    def get_episode_files(self, series_id: int) -> List[Dict]:
        """Fetch all episode files for a show from Sonarr"""
        endpoint = f"{self.base_url}/api/v3/episodefile?seriesId={series_id}"
        try:
            response = self.session.get(endpoint)
            response.raise_for_status()
            return response.json()
        except RequestException as e:
            logging.error("Failed to fetch episode files for series %s: %s", series_id, str(e))
            raise

    def update_show(self, series_id: int, series_data: Dict) -> bool:
        """Update a show in Sonarr"""
        endpoint = f"{self.base_url}/api/v3/series/{series_id}"
        try:
            response = self.session.put(endpoint, json=series_data)
            response.raise_for_status()
            return True
        except RequestException as e:
            logging.error(
                "Failed to update show %s. Response: %s. Error: %s",
                series_id,
                response.text if 'response' in locals() else '',
                str(e))
            return False

def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description='Sonarr Tag Updater')
    parser.add_argument(
        '--test',
        action='store_true',
        help='Run in test mode (only process first 5 shows)')
    parser.add_argument(
        '--version',
        action='store_true',
        help='Show version and exit')
    return parser.parse_args()

def get_config_from_env():
    """Load configuration from environment variables"""
    config = {
        'sonarr_url': os.environ['SONARR_URL'],
        'sonarr_api_key': os.environ['SONARR_API_KEY'],
        'log_level': os.getenv('LOG_LEVEL', 'INFO'),
        'score_threshold': int(os.getenv('SCORE_THRESHOLD', '100')),
        'motong_enabled': os.getenv('MOTONG', 'false').lower() == 'true'
    }

    # Validate required fields
    if not config['sonarr_url'] or not config['sonarr_api_key']:
        raise ValueError("Missing required environment variables: "
                       "SONARR_URL and SONARR_API_KEY must be set")

    logging.debug("Config loaded from environment successfully")
    return config

def get_score_tag(score: int, threshold: int) -> str:
    """Determine the appropriate score tag based on customFormatScore"""
    if score is None:
        return "no_score"
    if score < 0:
        return "negative_score"
    if score > threshold:
        return "positive_score"
    return "no_score"

VERSION = "1.0.0"

def process_show_tags(
        api: SonarrAPI,
        show: Dict,
        tag_map: Dict,
        score_threshold: int,
        config: Dict) -> bool:
    """Process and update tags for a single show"""
    show_update = show.copy()
    current_tags = set(show.get('tags', []))

    # Remove any existing score tags (by ID)
    score_tags = {
        'negative_score': '#ff0000',
        'positive_score': '#00ff00',
        'no_score': '#808080',
        'motong': '#800080',
        '4k': '#0000ff'
    }
    new_tag_ids = [tag_id for tag_id in current_tags
                 if not any(tag['id'] == tag_id and tag['label'] in score_tags
                          for tag in api.get_tags())]

    # Get episode files and find minimum score
    min_score = None
    has_4k = False
    has_motong = False

    try:
        episode_files = api.get_episode_files(show['id'])
        for ep_file in episode_files:
            # Track minimum score
            ep_score = ep_file.get('customFormatScore')
            if min_score is None or (ep_score is not None and ep_score < min_score):
                min_score = ep_score

            # Check for 4k
            quality = ep_file.get('quality', {})
            if quality.get('quality', {}).get('resolution') == 2160:
                has_4k = True

            # Check for motong
            if ep_file.get('releaseGroup', '').lower() == 'motong':
                has_motong = True
    except RequestException:
        logging.warning("Failed to get episode files for %s", show['title'])

    # Determine score tag
    new_tag_name = get_score_tag(min_score, score_threshold)
    logging.debug(
        "Show: %s - Min Score: %s - Tag: %s",
        show['title'],
        min_score,
        new_tag_name)
    new_tag_ids.append(tag_map[new_tag_name])

    # Add special tags if needed
    if has_motong and config['motong_enabled']:
        new_tag_ids.append(tag_map['motong'])
        logging.debug("Added motong tag for %s", show['title'])

    if has_4k:
        new_tag_ids.append(tag_map['4k'])
        logging.debug("Added 4k tag for %s", show['title'])

    # Only update if tags changed
    if set(new_tag_ids) != current_tags:
        show_update['tags'] = new_tag_ids
        return api.update_show(show['id'], show_update)
    return False


def ensure_required_tags(api: SonarrAPI) -> Dict:
    """Ensure required tags exist and return tag name to ID mapping"""
    all_tags = api.get_tags()
    tag_map = {tag['label']: tag['id'] for tag in all_tags}

    score_tags = {
        'negative_score': '#ff0000',
        'positive_score': '#00ff00',
        'no_score': '#808080',
        'motong': '#800080',
        '4k': '#0000ff'
    }

    for tag, color in score_tags.items():
        if tag not in tag_map:
            logging.info("Creating missing tag: %s", tag)
            new_tag = api.create_tag(tag, color)
            tag_map[tag] = new_tag['id']

    return tag_map

def main():
    """Main execution flow"""
    args = parse_args()

    if args.version:
        print(f"Sonarr Tag Updater v{VERSION}")
        sys.exit(0)

    config = get_config_from_env()
    setup_logging(config['log_level'])
    logging.info("Starting Sonarr Tag Updater v%s", VERSION)

    api = SonarrAPI(config['sonarr_url'], config['sonarr_api_key'])
    interval_minutes = int(os.getenv('INTERVAL_MINUTES', '20'))

    while True:
        try:
            tag_map = ensure_required_tags(api)
            shows = api.get_shows()

            if args.test:
                shows = shows[:5]
                logging.info("TEST MODE: Processing first 5 shows only")

            updated_count = sum(
                1 for show in shows
                if process_show_tags(api, show, tag_map, config['score_threshold'], config)
            )

            logging.info("Processing complete. Updated %s/%s shows", updated_count, len(shows))
            logging.info("Next run in %s minutes", interval_minutes)
            time.sleep(interval_minutes * 60)

        except (RequestException, ValueError) as e:
            logging.error("Script failed: %s", str(e))
            logging.info("Retrying in 5 minutes")
            time.sleep(300)

def setup_logging(log_level):
    """Configure logging"""
    log_format = '%(asctime)s - %(levelname)s - %(message)s'

    # Clear any existing handlers
    logging.root.handlers = []

    # Set up console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(logging.Formatter(log_format))

    # Configure root logger
    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=[console_handler]
    )

    logging.info("Logging initialized at level: %s", log_level)
    logging.debug("Debug logging enabled")

if __name__ == "__main__":
    main()
