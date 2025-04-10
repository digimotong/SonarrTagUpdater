#!/usr/bin/env python3
"""
Radarr Tag Updater
Fetches movies from Radarr API and updates tags.
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
    parser = argparse.ArgumentParser(description='Radarr Tag Updater')
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
        with open(config_path) as f:
            config = json.load(f)
        
        # Create output directory if needed
        output_dir = config.get('output_directory', 'results')
        os.makedirs(output_dir, exist_ok=True)
        
        return config
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
        print(f"Radarr Tag Updater v{VERSION}")
        sys.exit(0)
    
    # Load configuration
    config = load_config(args.config)
    
    # Apply argument overrides
    if args.format:
        config['output_format'] = args.format
    if args.log_level:
        config['log_level'] = args.log_level
    
    # Set global config
    RADARR_URL = config['radarr_url']
    RADARR_API_KEY = config['radarr_api_key']
    LOG_LEVEL = config.get('log_level', 'INFO')
    OUTPUT_DIR = config.get('output_directory', 'results')
    OUTPUT_FORMAT = config.get('output_format', 'json')
    if OUTPUT_FORMAT not in ['json', 'csv']:
        logging.warning(f"Invalid output_format '{OUTPUT_FORMAT}', defaulting to 'json'")
        OUTPUT_FORMAT = 'json'

    setup_logging(LOG_LEVEL)
    logging.info("Starting Radarr Tag Updater v%s", VERSION)
    
    try:
        # Initialize API client
        api = RadarrAPI(RADARR_URL, RADARR_API_KEY)
        
        # Fetch required data
        movies = api.get_movies()
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
            movies = movies[:5]
            logging.info("TEST MODE: Processing first 5 movies only")

        # Process and update movie tags
        score_threshold = config.get('score_threshold', 100)
        updated_count = 0
        all_updates = []

        for movie in movies:
            # Create a copy of the movie data to preserve all fields
            movie_update = movie.copy()
            current_tags = set(movie.get('tags', []))
            
            # Remove any existing score tags (by ID)
            new_tag_ids = [tag_id for tag_id in current_tags 
                         if not any(tag['id'] == tag_id and tag['label'] in score_tags 
                                  for tag in all_tags)]
            
            # Get movie file and score
            score = None
            if movie.get('movieFileId'):
                try:
                    movie_file = api.get_movie_file(movie['movieFileId'])
                    score = movie_file.get('customFormatScore')
                except RequestException:
                    logging.warning(f"Failed to get movie file for {movie['title']}")
            
            new_tag_name = get_score_tag(score, score_threshold)
            logging.debug(f"Movie: {movie['title']} - Score: {score} - Tag: {new_tag_name}")
            new_tag_ids.append(tag_map[new_tag_name])
            
            # Add motong tag if release group matches
            if movie.get('movieFileId'):
                try:
                    movie_file = api.get_movie_file(movie['movieFileId'])
                    if movie_file.get('releaseGroup', '').lower() == 'motong':
                        new_tag_ids.append(tag_map['motong'])
                        logging.debug(f"Added motong tag for {movie['title']}")
                    
                    # Add 4k tag if resolution is 2160p
                    quality = movie_file.get('quality', {})
                    if quality.get('quality', {}).get('resolution') == 2160:
                        new_tag_ids.append(tag_map['4k'])
                        logging.debug(f"Added 4k tag for {movie['title']}")
                except RequestException:
                    pass  # Already logged earlier
            
            # Only update if tags changed
            if set(new_tag_ids) != current_tags:
                movie_update['tags'] = new_tag_ids
                success = api.update_movie(movie['id'], movie_update)
                if success:
                    updated_count += 1
                    logging.debug(f"Updated tags for {movie['title']}")
                
                # Record update attempt (using tag names instead of IDs)
                all_updates.append({
                    'id': movie['id'],
                    'title': movie['title'],
                    'old_tags': [next((tag['label'] for tag in all_tags if tag['id'] == tag_id), tag_id)
                               for tag_id in current_tags],
                    'new_tags': [next((tag['label'] for tag in all_tags if tag['id'] == tag_id), tag_id)
                               for tag_id in new_tag_ids],
                    'score': score,
                    'threshold': score_threshold,
                    'success': success
                })

        logging.info(f"Processing complete. Updated {updated_count}/{len(movies)} movies")
        write_results(all_updates, OUTPUT_FORMAT, OUTPUT_DIR)
        
    except Exception as e:
        logging.error(f"Script failed: {str(e)}")
        sys.exit(1)

class RadarrAPI:
    """Client for Radarr API interactions"""
    
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            'X-Api-Key': self.api_key,
            'Accept': 'application/json'
        })
    
    def get_movies(self) -> List[Dict]:
        """Fetch all movies from Radarr"""
        endpoint = f"{self.base_url}/api/v3/movie"
        try:
            response = self.session.get(endpoint)
            response.raise_for_status()
            return response.json()
        except RequestException as e:
            logging.error(f"Failed to fetch movies: {str(e)}")
            raise

    def get_tags(self) -> List[Dict]:
        """Fetch all tags from Radarr"""
        endpoint = f"{self.base_url}/api/v3/tag"
        try:
            response = self.session.get(endpoint)
            response.raise_for_status()
            return response.json()
        except RequestException as e:
            logging.error(f"Failed to fetch tags: {str(e)}")
            raise

    def create_tag(self, label: str, color: str = "#808080") -> Dict:
        """Create a new tag in Radarr"""
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

    def get_movie_file(self, movie_file_id: int) -> Dict:
        """Fetch movie file details from Radarr"""
        endpoint = f"{self.base_url}/api/v3/moviefile/{movie_file_id}"
        try:
            response = self.session.get(endpoint)
            response.raise_for_status()
            return response.json()
        except RequestException as e:
            logging.error(f"Failed to fetch movie file {movie_file_id}: {str(e)}")
            raise

    def update_movie(self, movie_id: int, movie_data: Dict) -> bool:
        """Update a movie in Radarr"""
        endpoint = f"{self.base_url}/api/v3/movie/{movie_id}"
        try:
            response = self.session.put(endpoint, json=movie_data)
            response.raise_for_status()
            return True
        except RequestException as e:
            logging.error(f"Failed to update movie {movie_id}. Response: {response.text if 'response' in locals() else ''}. Error: {str(e)}")
            return False

def setup_logging(log_level):
    """Configure logging for cron job"""
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('radarr_tag_updater.log'),
            logging.StreamHandler()
        ]
    )

if __name__ == "__main__":
    main()
