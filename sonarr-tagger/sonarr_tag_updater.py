#!/usr/bin/env python3
"""
Sonarr Tag Updater
Fetches shows from Sonarr API and updates tags based on minimum episode scores.
"""

import os
import sys
import json
import logging
from typing import Dict, List
from datetime import datetime
import glob
import requests
from requests.exceptions import RequestException

def parse_args():
    """Parse command line arguments"""
    import argparse
    parser = argparse.ArgumentParser(description='Sonarr Tag Updater')
    parser.add_argument('--config', default='config.json',
                      help='Path to config file (default: config.json)')
    parser.add_argument('--test', action='store_true',
                      help='Run in test mode (only process first 5 movies)')
    parser.add_argument('--format', choices=['json', 'csv'],
                      help='Override output format from config')
    parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                      help='Override log level from config')
    parser.add_argument('--version', action='store_true',
                      help='Show version and exit')
    return parser.parse_args()

def load_config(config_path: str):
    """Load configuration from JSON file"""
    try:
        logging.debug(f"Attempting to load config from: {os.path.abspath(config_path)}")
        with open(config_path) as f:
            config = json.load(f)
        
        # Validate required fields
        required_keys = ['sonarr_url', 'sonarr_api_key']
        for key in required_keys:
            if key not in config:
                raise ValueError(f"Missing required config key: {key}")
        
        # Create output directory if needed
        output_dir = config.get('output_directory', 'results')
        os.makedirs(output_dir, exist_ok=True)
        
        logging.debug("Config loaded successfully")
        return config
    except json.JSONDecodeError as e:
        logging.error(f"Invalid JSON in config file: {str(e)}")
        sys.exit(1)
    except FileNotFoundError:
        logging.error(f"Config file not found at: {os.path.abspath(config_path)}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Failed to load config: {str(e)}")
        sys.exit(1)

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

def cleanup_old_files(output_dir: str, pattern: str, keep: int = 5):
    """Keep only the most recent files matching pattern"""
    files = glob.glob(os.path.join(output_dir, pattern))
    files.sort(key=os.path.getmtime, reverse=True)
    for old_file in files[keep:]:
        try:
            os.remove(old_file)
            logging.debug(f"Removed old file: {old_file}")
        except OSError as e:
            logging.warning(f"Failed to remove {old_file}: {e}")

def write_results(updates: list, output_format: str, output_dir: str = "results"):
    """Write update results to file"""
    if not updates:
        logging.info("No updates to write - skipping results file")
        return

    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(output_dir, f"updates_{timestamp}.{output_format.lower()}")
    
    if output_format == "json":
        with open(output_path, 'w') as f:
            json.dump(updates, f, indent=2)
    else:  # CSV
        import csv
        fieldnames = ['id', 'title', 'old_tags', 'new_tags', 'score', 'threshold', 'success']
        with open(output_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for update in updates:
                writer.writerow(update)
    logging.info(f"Wrote update results to {output_path}")
    cleanup_old_files(output_dir, f"updates_*.{output_format.lower()}")

def main():
    """Main execution flow"""
    args = parse_args()
    
    if args.version:
        print(f"Sonarr Tag Updater v{VERSION}")
        sys.exit(0)
    
    # Load configuration
    config = load_config(args.config)
    
    # Apply argument overrides
    if args.format:
        config['output_format'] = args.format
    if args.log_level:
        config['log_level'] = args.log_level
    
    # Set global config
    SONARR_URL = config['sonarr_url']
    SONARR_API_KEY = config['sonarr_api_key']
    LOG_LEVEL = config.get('log_level', 'INFO')
    OUTPUT_DIR = config.get('output_directory', 'results')
    OUTPUT_FORMAT = config.get('output_format', 'json')
    if OUTPUT_FORMAT not in ['json', 'csv']:
        logging.warning(f"Invalid output_format '{OUTPUT_FORMAT}', defaulting to 'json'")
        OUTPUT_FORMAT = 'json'

    setup_logging(LOG_LEVEL)
    logging.info("Starting Sonarr Tag Updater v%s", VERSION)
    
    try:
        # Initialize API client
        api = SonarrAPI(SONARR_URL, SONARR_API_KEY)
        
        # Fetch required data
        shows = api.get_shows()
        all_tags = api.get_tags()
        
        # Create tag name to ID mapping
        tag_map = {tag['label']: tag['id'] for tag in all_tags}
        
        # Ensure our required tags exist, create if missing
        score_tags = {
            'negative_score': '#ff0000',  # Red
            'positive_score': '#00ff00',  # Green
            'no_score': '#808080',        # Gray
            'motong': '#800080',         # Purple
            '4k': '#0000ff'              # Blue
        }
        for tag, color in score_tags.items():
            if tag not in tag_map:
                logging.info(f"Creating missing tag: {tag}")
                new_tag = api.create_tag(tag, color)
                tag_map[tag] = new_tag['id']
        
        if args.test:
            shows = shows[:5]
            logging.info("TEST MODE: Processing first 5 shows only")

        # Process and update show tags
        score_threshold = config.get('score_threshold', 100)
        updated_count = 0
        all_updates = []

        for show in shows:
            # Create a copy of the show data to preserve all fields
            show_update = show.copy()
            current_tags = set(show.get('tags', []))
            
            # Remove any existing score tags (by ID)
            new_tag_ids = [tag_id for tag_id in current_tags 
                         if not any(tag['id'] == tag_id and tag['label'] in score_tags 
                                  for tag in all_tags)]
            
            # Get all episode files and find minimum score
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
                logging.warning(f"Failed to get episode files for {show['title']}")
            
            # Determine score tag
            new_tag_name = get_score_tag(min_score, score_threshold)
            logging.debug(f"Show: {show['title']} - Min Score: {min_score} - Tag: {new_tag_name}")
            new_tag_ids.append(tag_map[new_tag_name])
            
            # Add motong tag if any episode has it
            if has_motong:
                new_tag_ids.append(tag_map['motong'])
                logging.debug(f"Added motong tag for {show['title']}")
            
            # Add 4k tag if any episode is 4k
            if has_4k:
                new_tag_ids.append(tag_map['4k'])
                logging.debug(f"Added 4k tag for {show['title']}")
            
            # Only update if tags changed
            if set(new_tag_ids) != current_tags:
                show_update['tags'] = new_tag_ids
                success = api.update_show(show['id'], show_update)
                if success:
                    updated_count += 1
                    logging.debug(f"Updated tags for {show['title']}")
                
                # Record update attempt (using tag names instead of IDs)
                all_updates.append({
                    'id': show['id'],
                    'title': show['title'],
                    'old_tags': [next((tag['label'] for tag in all_tags if tag['id'] == tag_id), tag_id)
                               for tag_id in current_tags],
                    'new_tags': [next((tag['label'] for tag in all_tags if tag['id'] == tag_id), tag_id)
                               for tag_id in new_tag_ids],
                    'score': min_score,
                    'threshold': score_threshold,
                    'success': success
                })

        logging.info(f"Processing complete. Updated {updated_count}/{len(shows)} shows")
        write_results(all_updates, OUTPUT_FORMAT, OUTPUT_DIR)
        
    except Exception as e:
        logging.error(f"Script failed: {str(e)}")
        sys.exit(1)

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
            logging.error(f"Failed to fetch shows: {str(e)}")
            raise

    def get_tags(self) -> List[Dict]:
        """Fetch all tags from Sonarr"""
        endpoint = f"{self.base_url}/api/v3/tag"
        try:
            response = self.session.get(endpoint)
            response.raise_for_status()
            return response.json()
        except RequestException as e:
            logging.error(f"Failed to fetch tags: {str(e)}")
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
            logging.error(f"Failed to create tag '{label}': {str(e)}")
            raise

    def get_episode_files(self, series_id: int) -> List[Dict]:
        """Fetch all episode files for a show from Sonarr"""
        endpoint = f"{self.base_url}/api/v3/episodefile?seriesId={series_id}"
        try:
            response = self.session.get(endpoint)
            response.raise_for_status()
            return response.json()
        except RequestException as e:
            logging.error(f"Failed to fetch episode files for series {series_id}: {str(e)}")
            raise

    def update_show(self, series_id: int, series_data: Dict) -> bool:
        """Update a show in Sonarr"""
        endpoint = f"{self.base_url}/api/v3/series/{series_id}"
        try:
            response = self.session.put(endpoint, json=series_data)
            response.raise_for_status()
            return True
        except RequestException as e:
            logging.error(f"Failed to update show {series_id}. Response: {response.text if 'response' in locals() else ''}. Error: {str(e)}")
            return False

def setup_logging(log_level):
    """Configure logging for cron job"""
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('sonarr_tag_updater.log'),
            logging.StreamHandler()
        ]
    )

if __name__ == "__main__":
    main()
