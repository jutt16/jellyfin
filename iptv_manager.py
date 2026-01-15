#!/usr/bin/env python3
"""
Combined Multi-Provider M3U to STRM Converter and Manager for Jellyfin

This single script provides all functionality for managing IPTV sources,
including a user-friendly menu, scheduling, automatic updates, content merging,
and failover playlist generation.
"""

import os
import sys
import time
import argparse
import requests
import re
import json
import subprocess
import hashlib
import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from collections import defaultdict
import shutil
import psutil
import socket
import threading
from urllib.parse import quote

# Optional imports with fallbacks
try:
    import asyncio
except ImportError:
    asyncio = None
    
try:
    import aiohttp
except ImportError:
    aiohttp = None
    
try:
    import redis
except ImportError:
    redis = None

try:
    from concurrent.futures import ThreadPoolExecutor
except ImportError:
    ThreadPoolExecutor = None
try:
    from flask import Flask, render_template_string, jsonify, request, send_from_directory
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False
    print("Flask not installed. Web viewer will not be available.")
    print("Install with: pip install flask")

# --- Configuration Constants ---
# Default paths optimized for Synology NAS with Jellyfin from SynoCommunity
# These can be customized during setup or by editing this file directly
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "m3u_config.json")

# Synology-optimized default paths
LOG_FILE = os.path.join(SCRIPT_DIR, "iptv_manager.log")  # Keep logs with script
BASE_DIR = "/volume2/jellyfin/iptv-content"  # Jellyfin media directory
LAST_UPDATE_FILE = os.path.join(SCRIPT_DIR, "m3u_last_update.json")  # Keep with script
WEB_PORT = 8765  # Port for built-in web viewer

# Performance and reliability constants
DEFAULT_REQUEST_TIMEOUT = 60  # seconds
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_FACTOR = 2
MAX_CONCURRENT_DOWNLOADS = 5
CACHE_TTL = 3600  # 1 hour in seconds
MAX_FILENAME_LENGTH = 200
CHUNK_SIZE = 8192  # For streaming downloads

# --- Logging Setup ---
try:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler()
        ]
    )
except PermissionError:
    print(f"Warning: Could not write to log file {LOG_FILE}. Logging to console only.")
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler()]
    )
logger = logging.getLogger(__name__)


# --- Core Converter Class ---
class MultiProviderM3UConverter:
    """Handles the core logic of downloading, merging, and converting M3U playlists."""

    def __init__(self, config_file=CONFIG_FILE):
        self.config_file = config_file
        self.base_dir = BASE_DIR
        self.last_update_file = LAST_UPDATE_FILE
        self.epg_file = "epg.xml"  # Default EPG filename
        self.request_timeout = DEFAULT_REQUEST_TIMEOUT
        self.ssl_verify = False  # Common for IPTV providers
        
        # Performance optimizations
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'VLC/3.0.16 LibVLC/3.0.16'})
        
        # Connection pooling
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=10,
            pool_maxsize=20,
            max_retries=requests.packages.urllib3.util.retry.Retry(
                total=DEFAULT_MAX_RETRIES,
                backoff_factor=DEFAULT_BACKOFF_FACTOR,
                status_forcelist=[500, 502, 503, 504]
            )
        )
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        
        # Thread pool for concurrent operations
        self.executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_DOWNLOADS) if ThreadPoolExecutor else None

    def load_config(self):
        """Load multiple provider configurations from JSON file."""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    # Set default base_dir from config if it exists
                    self.base_dir = config.get('output_dir', BASE_DIR)
                    return config
            except json.JSONDecodeError:
                logger.error("Invalid JSON in config file. Please fix or delete it.")
                sys.exit(1)
        return {}

    def save_config(self, config):
        """Save the configuration to the JSON file."""
        with open(self.config_file, 'w') as f:
            json.dump(config, f, indent=2)
        logger.info(f"Configuration saved to: {self.config_file}")

    def build_xtream_url(self, provider):
        """Build Xtream URL from provider configuration."""
        if provider.get('type') == 'xtream_url':
            return provider.get('url')
        elif provider.get('type') == 'xtream_creds':
            server = provider.get('server', '').rstrip('/')
            username = provider.get('username', '')
            password = provider.get('password', '')
            return f"{server}/get.php?username={username}&password={password}&type=m3u_plus&output=ts"
        elif provider.get('type') == 'direct_m3u':
            return provider.get('url')
        return None

    def download_epg(self, epg_sources):
        """Download all enabled EPG sources to temporary files."""
        if not epg_sources:
            logger.info("No EPG sources configured. Skipping EPG download.")
            return []

        downloaded_files = []
        enabled_sources = [s for s in epg_sources if s.get('enabled', True)]
        if not enabled_sources:
            logger.warning("No enabled EPG sources found.")
            return []

        for i, source in enumerate(enabled_sources):
            url = source.get('url')
            if not url: continue

            logger.info(f"Downloading EPG from: {url}")
            try:
                response = requests.get(url, timeout=60, verify=False)
                response.raise_for_status()
                temp_epg_path = os.path.join(self.base_dir, f"temp_epg_{i}.xml")
                with open(temp_epg_path, 'w', encoding='utf-8') as f:
                    f.write(response.text)
                logger.info(f"Temporary EPG data saved to {temp_epg_path}")
                downloaded_files.append(temp_epg_path)
            except requests.exceptions.RequestException as e:
                logger.error(f"Failed to download EPG data from {url}: {e}")
        
        return downloaded_files

    def _merge_epg_files(self, epg_files):
        """Merge multiple EPG XML files into one, removing duplicates."""
        if not epg_files:
            return

        logger.info(f"Merging {len(epg_files)} EPG source(s)...")
        merged_channels = {}
        merged_programmes = set()

        # Create a new root for the merged EPG
        merged_root = ET.Element("tv")

        for file_path in epg_files:
            try:
                tree = ET.parse(file_path)
                root = tree.getroot()

                for channel in root.findall('channel'):
                    channel_id = channel.get('id')
                    if channel_id and channel_id not in merged_channels:
                        merged_channels[channel_id] = channel

                for programme in root.findall('programme'):
                    prog_key = (programme.get('channel'), programme.get('start'), programme.get('stop'))
                    if prog_key not in merged_programmes:
                        merged_programmes.add(prog_key)
                        merged_root.append(programme)

            except ET.ParseError as e:
                logger.error(f"Failed to parse EPG file {file_path}: {e}")
            finally:
                os.remove(file_path) # Clean up temp file

        # Add all unique channels to the merged root
        for channel in merged_channels.values():
            merged_root.insert(0, channel) # Channels should typically be at the top

        # Write the final merged EPG file
        final_epg_path = os.path.join(self.base_dir, self.epg_file)
        tree = ET.ElementTree(merged_root)
        try:
            tree.write(final_epg_path, encoding='UTF-8', xml_declaration=True)
            logger.info(f"Successfully merged EPG data to {final_epg_path}")
        except Exception as e:
            logger.error(f"Failed to write merged EPG file: {e}")

    def download_m3u(self, provider_name, max_retries=3):
        """Download M3U content ONLY through proxy - no direct connections."""
        config = self.load_config()
        proxy_settings = config.get('proxy_settings', {})
        
        if not proxy_settings.get('enabled') or not proxy_settings.get('url'):
            logger.error(f"Proxy is required but not configured. Cannot download from {provider_name}.")
            logger.error("Please configure proxy settings in the menu before running updates.")
            return None
            
        proxy_url = proxy_settings['url']
        headers = {'User-Agent': 'VLC/3.0.16 LibVLC/3.0.16'}
        
        logger.info(f"Downloading M3U for {provider_name} through proxy: {proxy_url[:60]}...")
        requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
        
        for attempt in range(max_retries):
            try:
                response = requests.get(
                    proxy_url, 
                    timeout=self.request_timeout, 
                    verify=self.ssl_verify, 
                    headers=headers
                )
                response.raise_for_status()
                
                # Validate response content
                if not response.text or len(response.text.strip()) < 10:
                    raise ValueError("Empty or invalid M3U response")
                
                logger.info(f"Successfully downloaded M3U for {provider_name} through proxy.")
                return response.text
                
            except requests.exceptions.Timeout as e:
                logger.warning(f"Timeout on attempt {attempt + 1}/{max_retries} for {provider_name}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                    
            except requests.exceptions.ConnectionError as e:
                logger.warning(f"Connection error on attempt {attempt + 1}/{max_retries} for {provider_name}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    
            except requests.exceptions.HTTPError as e:
                logger.error(f"HTTP error for {provider_name}: {e}")
                if e.response.status_code >= 500 and attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    break  # Don't retry on client errors (4xx)
                    
            except ValueError as e:
                logger.error(f"Invalid response for {provider_name}: {e}")
                break
                
            except requests.exceptions.RequestException as e:
                logger.error(f"Request failed for {provider_name} on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
        
        logger.error(f"Failed to download M3U for {provider_name} after {max_retries} attempts")
        return None

    def create_content_id(self, name):
        """Create a unique but consistent content ID for deduplication."""
        # Normalize name: lowercase, remove special chars, spaces
        normalized = re.sub(r'\s+', ' ', name.lower())
        normalized = re.sub(r'[^\w\s]', '', normalized).strip()
        # Remove common quality/type indicators that vary between providers
        tags_to_remove = ['hd', 'fhd', 'uhd', '4k', 'sd', 'live', 'tv', 'fr', 'us', 'uk']
        for tag in tags_to_remove:
            normalized = re.sub(f'\\b{tag}\\b', '', normalized)
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        # Use a hash for a short, consistent ID
        return hashlib.md5(normalized.encode()).hexdigest()

    def _get_resolution_rank(self, name):
        """Assign a numerical rank to a stream based on resolution keywords in its name."""
        name_lower = name.lower()
        if any(kw in name_lower for kw in ['4k', 'uhd', '2160']): return 5
        if any(kw in name_lower for kw in ['1080', 'fhd']): return 4
        if any(kw in name_lower for kw in ['720', 'hd']): return 3
        if any(kw in name_lower for kw in ['576', 'sd']): return 2
        if any(kw in name_lower for kw in ['low', '360']): return 1
        return 0 # Default/Unknown

    def _parse_extinf_line(self, line):
        """Parse an #EXTINF line to extract name, group, EPG ID, and logo."""
        info = {'name': '', 'group': '', 'epg_id': '', 'logo': ''}
        try:
            # Name is the part after the last comma
            main_part, name_part = line.rsplit(',', 1)
            info['name'] = name_part.strip()

            # Extract attributes using regex for reliability
            tvg_id = re.search(r'tvg-id="([^"]*)"', main_part)
            if tvg_id: info['epg_id'] = tvg_id.group(1)

            tvg_logo = re.search(r'tvg-logo="([^"]*)"', main_part)
            if tvg_logo: info['logo'] = tvg_logo.group(1)

            group_title = re.search(r'group-title="([^"]*)"', main_part)
            if group_title: info['group'] = group_title.group(1)

        except ValueError:
            # Fallback for lines without a comma
            info['name'] = line.strip()
        except Exception as e:
            logger.warning(f"Error parsing EXTINF line: {e}")
            info['name'] = "Unknown Channel"
        return info

    def categorize_content(self, name, group_title=""):
        """Smart categorization of content (Movies, Series, Live, Catchup)."""
        if not name:
            return 'Live'  # Default fallback
            
        name_lower = name.lower()
        group_lower = group_title.lower() if group_title else ""

        # Keywords for categorization
        catchup_kw = ['catchup', 'timeshift', 'replay']
        movie_kw = ['movie', 'film', 'cinema', 'vod']
        series_kw = ['series', 'tv show', 'season', 's01', 's02', 'episode', 'e01', 'e02']

        # Check group title first for explicit categorization
        if group_lower and any(kw in group_lower for kw in catchup_kw):
            return 'Catchup'
        if group_lower and any(kw in group_lower for kw in movie_kw):
            return 'Movies'
        if group_lower and any(kw in group_lower for kw in series_kw):
            return 'Series'

        # Then check channel name
        if any(kw in name_lower for kw in movie_kw):
            return 'Movies'
        if any(kw in name_lower for kw in series_kw):
            return 'Series'

        # Default to Live TV if no other category matches
        return 'Live'

    def parse_m3u_content(self, m3u_content, provider, group_filters, channel_mapping):
        """Parse M3U content, apply filters, and categorize into a structured dictionary."""
        all_content = defaultdict(lambda: defaultdict(dict))
        lines = m3u_content.strip().split('\n')
        current_info = {}

        for i, line in enumerate(lines):
            line = line.strip()
            if line.startswith('#EXTINF'):
                current_info = self._parse_extinf_line(line)
            elif line and not line.startswith('#'):
                stream_url = line
                if not current_info or not current_info.get('name'):
                    continue # Skip if there's no preceding #EXTINF info

                # Apply channel mapping
                original_name = current_info['name']
                if original_name in channel_mapping:
                    mapping = channel_mapping[original_name]
                    current_info['name'] = mapping.get('name', original_name)
                    current_info['group'] = mapping.get('group', current_info['group'])
                    current_info['logo'] = mapping.get('logo', current_info['logo'])

                # Apply group filters
                group = current_info.get('group', 'Uncategorized')
                filter_mode = group_filters.get('mode', 'exclude')
                filter_list = group_filters.get('groups', [])
                if (filter_mode == 'exclude' and group in filter_list) or \
                   (filter_mode == 'include' and group not in filter_list):
                    continue

                category = self.categorize_content(current_info['name'], group)
                content_id = self.create_content_id(current_info['name'])

                stream_details = {
                    'url': stream_url,
                    'provider': provider['name'],
                    'resolution_rank': self._get_resolution_rank(current_info['name'])
                }

                if content_id not in all_content[category]:
                    all_content[category][content_id] = {
                        'name': current_info['name'],
                        'group': group,
                        'epg_id': current_info['epg_id'],
                        'logo': current_info['logo'],
                        'streams': [],
                        'providers': []
                    }
                
                all_content[category][content_id]['streams'].append(stream_details)
                if provider['name'] not in all_content[category][content_id]['providers']:
                    all_content[category][content_id]['providers'].append(provider['name'])
                
                current_info = {}

        return all_content


    def _check_for_updates(self, providers):
        """Check proxy M3U for changes using content hashing."""
        config = self.load_config()
        proxy_settings = config.get('proxy_settings', {})
        
        if not proxy_settings.get('enabled') or not proxy_settings.get('url'):
            logger.warning("Proxy not configured - cannot check for updates")
            return True  # Force update if proxy not configured
            
        try:
            with open(self.last_update_file, 'r') as f:
                last_hashes = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            last_hashes = {}

        proxy_url = proxy_settings['url']
        logger.info("Checking for updates through proxy...")
        
        try:
            response = requests.get(proxy_url, timeout=30, verify=self.ssl_verify, stream=True)
            response.raise_for_status()
            hasher = hashlib.md5()
            for chunk in response.iter_content(chunk_size=8192):
                hasher.update(chunk)
            current_hash = hasher.hexdigest()
            
            if last_hashes.get('proxy_content') != current_hash:
                logger.info("Update detected through proxy.")
                last_hashes['proxy_content'] = current_hash
                with open(self.last_update_file, 'w') as f:
                    json.dump(last_hashes, f)
                return True
            else:
                logger.info("No changes detected through proxy.")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Could not check for updates through proxy: {e}")
            return True  # Assume update needed if we can't check

    def _cleanup_old_files(self, generated_files):
        """Remove any STRM files that weren't generated in the current run."""
        logger.info("Cleaning up old files...")
        base_dir_files = set()
        for root, _, files in os.walk(self.base_dir):
            for file in files:
                if file.endswith('.strm'):
                    base_dir_files.add(os.path.join(root, file))

        to_delete = base_dir_files - generated_files
        for file_path in to_delete:
            try:
                os.remove(file_path)
                logger.info(f"Removed old file: {file_path}")
            except OSError as e:
                logger.error(f"Error removing file {file_path}: {e}")

        # Clean up empty directories
        for root, dirs, _ in os.walk(self.base_dir, topdown=False):
            for d in dirs:
                dir_path = os.path.join(root, d)
                if not os.listdir(dir_path):
                    os.rmdir(dir_path)
                    logger.info(f"Removed empty directory: {dir_path}")

    def _sanitize_filename(self, filename):
        """Safely sanitize filename to prevent path traversal attacks."""
        if not filename:
            return "unknown"
        
        # Remove path separators and dangerous characters
        sanitized = re.sub(r'[/\\*?"<>|:.]', '', filename)
        sanitized = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', sanitized)  # Remove control characters
        
        # Prevent reserved names on Windows
        reserved_names = {'CON', 'PRN', 'AUX', 'NUL', 'COM1', 'COM2', 'COM3', 'COM4', 
                         'COM5', 'COM6', 'COM7', 'COM8', 'COM9', 'LPT1', 'LPT2', 'LPT3', 
                         'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'}
        if sanitized.upper() in reserved_names:
            sanitized = f"_{sanitized}"
        
        # Limit length and ensure not empty
        sanitized = sanitized[:200].strip()
        return sanitized if sanitized else "unnamed"

    def _validate_stream_url(self, url):
        """Validate stream URL for security."""
        if not url or not isinstance(url, str):
            return False
        
        # Check for basic URL structure
        if not (url.startswith('http://') or url.startswith('https://')):
            return False
        
        # Prevent local file access
        if any(pattern in url.lower() for pattern in ['file://', 'localhost', '127.0.0.1', '0.0.0.0']):
            logger.warning(f"Blocked potentially unsafe URL: {url[:50]}...")
            return False
        
        return True

    def _generate_strm_file(self, category, item_name, stream_url):
        """Generate a single STRM file, sanitizing the filename."""
        if not self._validate_stream_url(stream_url):
            logger.error(f"Invalid or unsafe stream URL rejected: {stream_url[:50]}...")
            return None
        
        sanitized_name = self._sanitize_filename(item_name)
        
        # Validate category path
        if not re.match(r'^[a-zA-Z0-9_\-\s]+$', category):
            logger.error(f"Invalid category name: {category}")
            return None
        
        category_dir = os.path.join(self.base_dir, category)
        
        # Ensure we're not writing outside base directory
        if not os.path.abspath(category_dir).startswith(os.path.abspath(self.base_dir)):
            logger.error(f"Path traversal attempt blocked: {category_dir}")
            return None
        
        os.makedirs(category_dir, exist_ok=True)
        file_path = os.path.join(category_dir, f"{sanitized_name}.strm")
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(stream_url)
            return file_path
        except IOError as e:
            logger.error(f"Could not write STRM file {file_path}: {e}")
            return None

    def _generate_lightweight_m3u(self, live_content):
        """Generate a lightweight M3U for EPG mapping in Jellyfin."""
        m3u_path = os.path.join(self.base_dir, 'live_channels.m3u')
        logger.info(f"Generating lightweight M3U for EPG mapping at: {m3u_path}")
        try:
            with open(m3u_path, 'w', encoding='utf-8') as f:
                f.write('#EXTM3U\n')
                sorted_channels = sorted(live_content.values(), key=lambda x: x['name'])
                for item in sorted_channels:
                    best_stream = max(item['streams'], key=lambda x: x['resolution_rank'])
                    f.write(f'#EXTINF:-1 tvg-id="{item["epg_id"]}" tvg-logo="{item["logo"]}" group-title="{item["group"]}",{item["name"]}\n')
                    f.write(f'{best_stream["url"]}\n')
        except IOError as e:
            logger.error(f"Could not write lightweight M3U file: {e}")

    def run_update(self, force=False, dry_run=False):
        """The main process to update all content."""
        logger.info("Starting update process...")
        config = self.load_config()
        
        # Check proxy configuration first
        proxy_settings = config.get('proxy_settings', {})
        if not proxy_settings.get('enabled') or not proxy_settings.get('url'):
            logger.error("Proxy is required but not configured.")
            logger.error("Please configure proxy settings before running updates.")
            return

        if not force and not self._check_for_updates(config.get('providers', [])):
            logger.info("No remote changes detected. Skipping update.")
            return

        # EPG Handling
        epg_sources = config.get('epg_sources', [])
        temp_epg_files = self.download_epg(epg_sources)
        if temp_epg_files:
            self._merge_epg_files(temp_epg_files)

        # M3U Processing - single proxy download for all providers
        m3u_content = self.download_m3u("All Providers")
        if not m3u_content:
            logger.error("Failed to download M3U content through proxy.")
            return

        all_providers_content = defaultdict(lambda: defaultdict(dict))
        
        # Parse content with provider-specific settings
        providers = config.get('providers', [])
        if providers:
            # Use first enabled provider's settings for parsing
            active_provider = next((p for p in providers if p.get('enabled', True)), providers[0] if providers else None)
            if active_provider:
                parsed_content = self.parse_m3u_content(
                    m3u_content,
                    active_provider,
                    config.get('group_filters', {}),
                    config.get('channel_mapping', {})
                )
                all_providers_content.update(parsed_content)

        if dry_run:
            logger.info("--- Dry Run Summary ---")
            for category, items in all_providers_content.items():
                logger.info(f"{category}: {len(items)} items found.")
            return

        # File Generation
        generated_files = set()
        for category, items in all_providers_content.items():
            for content_id, data in items.items():
                if data['streams']:
                    best_stream = max(data['streams'], key=lambda x: x['resolution_rank'])
                    file_path = self._generate_strm_file(category, data['name'], best_stream['url'])
                    if file_path:
                        generated_files.add(file_path)
        
        self._cleanup_old_files(generated_files)
        
        if 'Live' in all_providers_content:
            self._generate_lightweight_m3u(all_providers_content['Live'])

        logger.info("Update process completed successfully.")


# --- Async Failover Monitoring Class ---
class AsyncFailoverManager:
    """Handles async failover monitoring for enterprise deployments."""
    
    def __init__(self):
        self.services = {
            'jellyfin': {'url': 'http://localhost:8096/health', 'critical': True},
            'threadfin': {'url': 'http://localhost:34400', 'critical': False},
            'nginx': {'url': 'http://localhost:80', 'critical': False},
            'redis': {'url': 'http://localhost:6379', 'critical': False}
        }
        self.failure_counts = {}
        self.max_failures = 3
        self.check_interval = 30
        self.running = False
        
    async def start_failover_monitoring(self):
        """Start async failover monitoring system."""
        self.running = True
        logger.info("Starting async failover monitoring...")
        
        await asyncio.gather(
            self.monitor_services(),
            self.handle_failover_events(),
            self.cleanup_stale_data()
        )
    
    async def monitor_services(self):
        """Monitor all services for health and trigger failover if needed."""
        while self.running:
            try:
                tasks = []
                for service_name, config in self.services.items():
                    tasks.append(self.check_service_health(service_name, config))
                
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                for i, (service_name, result) in enumerate(zip(self.services.keys(), results)):
                    if isinstance(result, Exception):
                        logger.error(f"Health check failed for {service_name}: {result}")
                        await self.handle_service_failure(service_name)
                    elif not result:
                        await self.handle_service_failure(service_name)
                    else:
                        # Reset failure count on success
                        self.failure_counts[service_name] = 0
                
                await asyncio.sleep(self.check_interval)
                
            except Exception as e:
                logger.error(f"Service monitoring error: {e}")
                await asyncio.sleep(10)
    
    async def check_service_health(self, service_name, config):
        """Check health of individual service."""
        if aiohttp:
            try:
                timeout = aiohttp.ClientTimeout(total=10)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(config['url']) as response:
                        return response.status in [200, 204]
            except Exception as e:
                logger.debug(f"aiohttp health check failed for {service_name}: {e}")
                return False
        else:
            # Fallback to requests if aiohttp not available
            try:
                response = requests.get(config['url'], timeout=10)
                return response.status_code in [200, 204]
            except Exception as e:
                logger.debug(f"requests health check failed for {service_name}: {e}")
                return False
    
    async def handle_service_failure(self, service_name):
        """Handle service failure and trigger failover if threshold reached."""
        self.failure_counts[service_name] = self.failure_counts.get(service_name, 0) + 1
        
        if self.failure_counts[service_name] >= self.max_failures:
            logger.warning(f"Service {service_name} has failed {self.max_failures} times, triggering failover")
            await self.trigger_failover(service_name)
    
    async def trigger_failover(self, failed_service):
        """Trigger failover procedures for failed service."""
        try:
            logger.critical(f"Triggering failover for {failed_service}")
            
            if failed_service == 'jellyfin':
                await self.restart_jellyfin()
            elif failed_service == 'threadfin':
                await self.restart_docker_service('threadfin-proxy')
            elif failed_service == 'nginx':
                await self.restart_docker_service('jellyfin-nginx')
            elif failed_service == 'redis':
                await self.restart_docker_service('jellyfin-cache')
            
            # Reset failure count after failover attempt
            self.failure_counts[failed_service] = 0
            
        except Exception as e:
            logger.error(f"Failover failed for {failed_service}: {e}")
    
    async def restart_jellyfin(self):
        """Restart Jellyfin service (Synology)."""
        try:
            process = await asyncio.create_subprocess_exec(
                'sudo', 'synoservice', '--restart', 'pkgctl-Jellyfin',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                logger.info("Jellyfin service restarted successfully")
            else:
                logger.error(f"Jellyfin restart failed: {stderr.decode()}")
                
        except Exception as e:
            logger.error(f"Error restarting Jellyfin: {e}")
    
    async def restart_docker_service(self, container_name):
        """Restart Docker container service."""
        try:
            process = await asyncio.create_subprocess_exec(
                'docker', 'restart', container_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                logger.info(f"Docker service {container_name} restarted successfully")
            else:
                logger.error(f"Docker restart failed for {container_name}: {stderr.decode()}")
                
        except Exception as e:
            logger.error(f"Error restarting Docker service {container_name}: {e}")
    
    async def handle_failover_events(self):
        """Handle failover events and notifications."""
        while self.running:
            try:
                # Check for manual failover triggers
                # This could be extended to listen to Redis pub/sub or other event systems
                await asyncio.sleep(60)
                
            except Exception as e:
                logger.error(f"Failover event handling error: {e}")
                await asyncio.sleep(30)
    
    async def cleanup_stale_data(self):
        """Cleanup stale monitoring data."""
        while self.running:
            try:
                # Reset failure counts periodically to prevent permanent blacklisting
                current_time = time.time()
                
                # Reset counts every hour
                if hasattr(self, '_last_cleanup') and current_time - self._last_cleanup > 3600:
                    self.failure_counts = {}
                    self._last_cleanup = current_time
                elif not hasattr(self, '_last_cleanup'):
                    self._last_cleanup = current_time
                
                await asyncio.sleep(1800)  # Run every 30 minutes
                
            except Exception as e:
                logger.error(f"Cleanup error: {e}")
                await asyncio.sleep(300)
    
    def stop_monitoring(self):
        """Stop the failover monitoring system."""
        self.running = False
        logger.info("Failover monitoring stopped")


# --- System Health & Management Class ---
class SystemHealthManager:
    """Handles system health monitoring, service management, and performance optimization."""
    
    def __init__(self):
        self.services = {
            'jellyfin': {'port': 8096, 'name': 'pkgctl-Jellyfin', 'type': 'synology'},
            'threadfin': {'port': 34400, 'name': 'threadfin-proxy', 'type': 'docker'},
            'nginx': {'port': 80, 'name': 'jellyfin-nginx', 'type': 'docker'},
            'redis': {'port': 6379, 'name': 'jellyfin-cache', 'type': 'docker'}
        }
        
    def check_service_health(self, service_name):
        """Check if a service is healthy by testing its port."""
        if service_name not in self.services:
            return False
            
        service = self.services[service_name]
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex(('localhost', service['port']))
            sock.close()
            return result == 0
        except:
            return False
    
    def get_service_status(self, service_name):
        """Get detailed service status."""
        if service_name not in self.services:
            return {'status': 'unknown', 'details': 'Service not configured'}
            
        service = self.services[service_name]
        health = self.check_service_health(service_name)
        
        status = {
            'name': service_name,
            'healthy': health,
            'port': service['port'],
            'type': service['type']
        }
        
        if service['type'] == 'docker':
            try:
                result = subprocess.run(['docker', 'ps', '--filter', f'name={service["name"]}', 
                                       '--format', '{{.Status}}'], 
                                      capture_output=True, text=True, timeout=10)
                status['docker_status'] = result.stdout.strip() if result.returncode == 0 else 'Not running'
            except:
                status['docker_status'] = 'Unknown'
        elif service['type'] == 'synology':
            try:
                result = subprocess.run(['synoservice', '--status', service['name']], 
                                      capture_output=True, text=True, timeout=10)
                status['synology_status'] = 'Running' if 'start' in result.stdout else 'Stopped'
            except:
                status['synology_status'] = 'Unknown'
        
        return status
    
    def restart_service(self, service_name):
        """Restart a specific service."""
        if service_name not in self.services:
            return False, "Service not configured"
            
        service = self.services[service_name]
        try:
            if service['type'] == 'docker':
                result = subprocess.run(['docker', 'restart', service['name']], 
                                      capture_output=True, text=True, timeout=30)
                return result.returncode == 0, result.stderr if result.returncode != 0 else "Success"
            elif service['type'] == 'synology':
                result = subprocess.run(['sudo', 'synoservice', '--restart', service['name']], 
                                      capture_output=True, text=True, timeout=30)
                return result.returncode == 0, result.stderr if result.returncode != 0 else "Success"
        except Exception as e:
            return False, str(e)
        
        return False, "Unknown service type"
    
    def get_system_stats(self):
        """Get system performance statistics."""
        try:
            stats = {
                'cpu_percent': psutil.cpu_percent(interval=1),
                'memory': psutil.virtual_memory()._asdict(),
                'disk': psutil.disk_usage('/volume2')._asdict(),
                'network': psutil.net_io_counters()._asdict(),
                'uptime': time.time() - psutil.boot_time()
            }
            
            # Convert bytes to human readable
            for key in ['total', 'available', 'used']:
                if key in stats['memory']:
                    stats['memory'][f'{key}_gb'] = round(stats['memory'][key] / (1024**3), 2)
            
            for key in ['total', 'used', 'free']:
                if key in stats['disk']:
                    stats['disk'][f'{key}_gb'] = round(stats['disk'][key] / (1024**3), 2)
            
            return stats
        except Exception as e:
            logger.error(f"Failed to get system stats: {e}")
            return {}
    
    def check_redis_cache(self):
        """Check Redis cache performance."""
        if not redis:
            return {'connected': False, 'error': 'Redis module not installed'}
            
        try:
            r = redis.Redis(host='localhost', port=6379, socket_timeout=5)
            info = r.info()
            
            hits = info.get('keyspace_hits', 0)
            misses = info.get('keyspace_misses', 0)
            hit_rate = (hits / (hits + misses) * 100) if (hits + misses) > 0 else 0
            
            return {
                'connected': True,
                'memory_usage': info.get('used_memory_human', 'Unknown'),
                'connected_clients': info.get('connected_clients', 0),
                'hit_rate': round(hit_rate, 2),
                'total_commands': info.get('total_commands_processed', 0)
            }
        except Exception as e:
            return {'connected': False, 'error': f'Redis connection failed: {e}'}
    
    def optimize_system(self):
        """Apply system optimizations for streaming."""
        optimizations = []
        
        try:
            # TCP optimizations for streaming
            tcp_settings = [
                'net.core.rmem_max = 134217728',
                'net.core.wmem_max = 134217728', 
                'net.ipv4.tcp_window_scaling = 1',
                'net.ipv4.tcp_congestion_control = bbr'
            ]
            
            for setting in tcp_settings:
                try:
                    subprocess.run(['sudo', 'sysctl', '-w', setting], 
                                 capture_output=True, check=True)
                    optimizations.append(f"Applied: {setting}")
                except:
                    optimizations.append(f"Failed: {setting}")
            
            return optimizations
        except Exception as e:
            return [f"Optimization failed: {e}"]


# --- UI Manager Class ---
class IPTVManager:
    """Handles the command-line interface and user interactions."""

    def __init__(self):
        self.converter = MultiProviderM3UConverter()
        self.health_manager = SystemHealthManager()
        self.failover_manager = AsyncFailoverManager()
        self.web_viewer = WebViewer(self.converter)
        self.config = self.converter.load_config()
        self.c = {
            'red': '\033[91m', 'green': '\033[92m', 'yellow': '\033[93m',
            'blue': '\033[94m', 'magenta': '\033[95m', 'cyan': '\033[96m',
            'nc': '\033[0m', 'bold': '\033[1m'
        }

    def _get_input(self, prompt, default=None):
        if default:
            return input(f"{self.c['cyan']}{prompt}{self.c['nc']} [{default}]: ") or default
        return input(f"{self.c['cyan']}{prompt}{self.c['nc']}: ")

    def _print_header(self):
        print("\n" + "="*50)
        print(f"{self.c['bold']}{self.c['magenta']} IPTV Manager for Jellyfin {self.c['nc']}".center(60))
        print("="*50)

    def manage_proxy_settings(self):
        """CLI to manage proxy settings - REQUIRED for operation."""
        self._print_header()
        print("--- Proxy Settings (REQUIRED) ---")
        print(f"{self.c['yellow']}Note: This script requires a proxy (Threadfin/iptv-proxy) for remote access.{self.c['nc']}")
        self.config.setdefault('proxy_settings', {'enabled': False, 'url': ''})
        proxy_settings = self.config['proxy_settings']

        while True:
            status = f"{self.c['green']}Enabled{self.c['nc']}" if proxy_settings.get('enabled') else f"{self.c['red']}Disabled{self.c['nc']}"
            url = proxy_settings.get('url') or "Not set"
            print(f"\nCurrent Status: {status}")
            print(f"Proxy URL: {url}")
            print("\n1. Enable Proxy (Required)")
            print("2. Set Proxy URL")
            print("3. Disable Proxy (Not Recommended)")
            print("4. Return to Main Menu")
            choice = self._get_input("Enter your choice")

            if choice == '1':
                proxy_settings['enabled'] = True
                self.converter.save_config(self.config)
                print(f"{self.c['green']}Proxy enabled.{self.c['nc']}")
            elif choice == '2':
                new_url = self._get_input("Enter the full proxy M3U URL (e.g., from Threadfin)")
                if new_url.startswith('http'):
                    proxy_settings['url'] = new_url
                    proxy_settings['enabled'] = True  # Auto-enable when URL is set
                    self.converter.save_config(self.config)
                    print(f"{self.c['green']}Proxy URL updated and enabled.{self.c['nc']}")
                else:
                    print(f"{self.c['red']}Invalid URL. Please enter a valid HTTP/HTTPS URL.{self.c['nc']}")
            elif choice == '3':
                proxy_settings['enabled'] = False
                self.converter.save_config(self.config)
                print(f"{self.c['yellow']}Proxy disabled. Updates will not work without proxy.{self.c['nc']}")
            elif choice == '4':
                break

    def manage_channel_mappings(self):
        """CLI to manage custom channel mappings."""
        self._print_header()
        print("--- Advanced Channel Mapping ---")
        self.config.setdefault('channel_mapping', {})
        mappings = self.config['channel_mapping']

        while True:
            print("\n1. List Current Mappings")
            print("2. Add/Edit a Mapping")
            print("3. Remove a Mapping")
            print("4. Return to Main Menu")
            choice = self._get_input("Enter your choice")

            if choice == '1':
                if not mappings:
                    print(f"\n{self.c['yellow']}No channel mappings configured.{self.c['nc']}")
                else:
                    print("\n--- Current Mappings ---")
                    for original_name, map_data in mappings.items():
                        print(f"- Original: '{original_name}'")
                        if 'name' in map_data: print(f"  └─ New Name:  '{map_data['name']}'")
                        if 'group' in map_data: print(f"  └─ New Group: '{map_data['group']}'")
                        if 'logo' in map_data: print(f"  └─ New Logo:  '{map_data['logo']}'")
        
            elif choice == '2':
                original_name = self._get_input("\nEnter the original channel name to map (case-sensitive)")
                if not original_name: continue

                new_mapping = mappings.get(original_name, {})
                print(f"\nEditing mapping for '{original_name}'. Leave blank to keep current value.")

                new_name = self._get_input(f"New channel name", new_mapping.get('name', ''))
                if new_name: new_mapping['name'] = new_name

                new_group = self._get_input(f"New group title", new_mapping.get('group', ''))
                if new_group: new_mapping['group'] = new_group

                new_logo = self._get_input(f"New logo URL", new_mapping.get('logo', ''))
                if new_logo: new_mapping['logo'] = new_logo

                if new_mapping:
                    mappings[original_name] = new_mapping
                    self.converter.save_config(self.config)
                    print(f"{self.c['green']}Mapping for '{original_name}' saved.{self.c['nc']}")
                else:
                    print(f"{self.c['yellow']}No changes made.{self.c['nc']}")

            elif choice == '3':
                original_name = self._get_input("\nEnter original channel name to remove mapping for")
                if original_name in mappings:
                    del mappings[original_name]
                    self.converter.save_config(self.config)
                    print(f"{self.c['green']}Mapping for '{original_name}' removed.{self.c['nc']}")
                else:
                    print(f"{self.c['red']}Mapping not found.{self.c['nc']}")

            elif choice == '4':
                break
            else:
                print(f"{self.c['red']}Invalid choice.{self.c['nc']}")

    def backup_restore_config(self):
        """CLI to backup or restore the configuration file."""
        self._print_header()
        print("--- Backup & Restore Configuration ---")
        print("\n1. Backup Current Configuration")
        print("2. Restore Configuration from Backup")
        print("3. Return to Main Menu")
        choice = self._get_input("Enter your choice")

        if choice == '1':
            backup_dir = self._get_input("Enter directory to save backup file", os.path.join(SCRIPT_DIR, 'backups'))
            os.makedirs(backup_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = os.path.join(backup_dir, f"m3u_config_backup_{timestamp}.json")
            try:
                import shutil
                shutil.copy(self.converter.config_file, backup_file)
                print(f"{self.c['green']}Configuration successfully backed up to: {backup_file}{self.c['nc']}")
            except Exception as e:
                print(f"{self.c['red']}Backup failed: {e}{self.c['nc']}")

        elif choice == '2':
            backup_dir = self._get_input("Enter directory where backups are stored", os.path.join(SCRIPT_DIR, 'backups'))
            if not os.path.isdir(backup_dir):
                print(f"{self.c['red']}Backup directory not found.{self.c['nc']}")
                return
            
            backups = [f for f in os.listdir(backup_dir) if f.endswith('.json')]
            if not backups:
                print(f"{self.c['yellow']}No backup files found in {backup_dir}.{self.c['nc']}")
                return

            print("\n--- Available Backups ---")
            for i, backup in enumerate(backups, 1):
                print(f"{i}. {backup}")
            
            try:
                file_choice = int(self._get_input("Enter number of the backup to restore")) - 1
                if 0 <= file_choice < len(backups):
                    backup_file = os.path.join(backup_dir, backups[file_choice])
                    if self._get_input(f"Restore {backups[file_choice]}? This will overwrite current config. (y/n)", 'n').lower() == 'y':
                        shutil.copy(backup_file, self.converter.config_file)
                        self.config = self.converter.load_config() # Reload config
                        print(f"{self.c['green']}Configuration successfully restored.{self.c['nc']}")
                else:
                    print(f"{self.c['red']}Invalid selection.{self.c['nc']}")
            except ValueError:
                print(f"{self.c['red']}Invalid input.{self.c['nc']}")

        elif choice == '3':
            return

    def setup_cron(self):
        """Provides instructions for setting up automated updates on Synology NAS."""
        self._print_header()
        print("--- Setup Cron Automation ---")
        print(f"{self.c['yellow']}Instructions for Synology NAS Task Scheduler:{self.c['nc']}")
        
        script_path = os.path.abspath(__file__)
        python_path = sys.executable
        
        print(f"\n{self.c['bold']}1. Open DSM Control Panel > Task Scheduler{self.c['nc']}")
        print(f"{self.c['bold']}2. Create > Scheduled Task > User-defined script{self.c['nc']}")
        print(f"{self.c['bold']}3. General Tab:{self.c['nc']}")
        print(f"   - Task: IPTV Manager Auto Update")
        print(f"   - User: root (or your admin user)")
        print(f"   - Enabled: ✓")
        
        print(f"\n{self.c['bold']}4. Schedule Tab:{self.c['nc']}")
        print(f"   - Run on the following days: Daily")
        print(f"   - First run time: 02:00 (or preferred time)")
        print(f"   - Frequency: Every 6 hours (or preferred)")
        
        print(f"\n{self.c['bold']}5. Task Settings Tab:{self.c['nc']}")
        print(f"   - Send run details by email: Optional")
        print(f"   - User-defined script:")
        print(f"{self.c['green']}")
        print(f"   {python_path} {script_path} --auto-mode")
        print(f"{self.c['nc']}")
        
        print(f"\n{self.c['bold']}Alternative Commands:{self.c['nc']}")
        print(f"Force update (ignores change detection):")
        print(f"{self.c['cyan']}   {python_path} {script_path} --auto-mode --force{self.c['nc']}")
        print(f"Continuous mode (runs every 6 hours):")
        print(f"{self.c['cyan']}   {python_path} {script_path} --schedule 6h{self.c['nc']}")
        
        print(f"\n{self.c['yellow']}Note: Ensure proxy settings are configured before enabling automation.{self.c['nc']}")
        
        if self._get_input("Copy command to clipboard? (y/n)", "n").lower() == 'y':
            try:
                command = f"{python_path} {script_path} --auto-mode"
                subprocess.run(['clip'], input=command.encode(), check=True)
                print(f"{self.c['green']}Command copied to clipboard!{self.c['nc']}")
            except:
                print(f"{self.c['yellow']}Could not copy to clipboard. Please copy manually.{self.c['nc']}")

    def system_health_status(self):
        """Display comprehensive system health status."""
        self._print_header()
        print("--- System Health & Performance Status ---")
        
        # Service Status
        print(f"\n{self.c['bold']}🔧 Service Status:{self.c['nc']}")
        for service_name in self.health_manager.services.keys():
            status = self.health_manager.get_service_status(service_name)
            health_icon = "✅" if status['healthy'] else "❌"
            print(f"{health_icon} {service_name.title()}: Port {status['port']} - {'Healthy' if status['healthy'] else 'Unhealthy'}")
            
            if status['type'] == 'docker' and 'docker_status' in status:
                print(f"   └─ Docker: {status['docker_status']}")
            elif status['type'] == 'synology' and 'synology_status' in status:
                print(f"   └─ Synology: {status['synology_status']}")
        
        # System Performance
        print(f"\n{self.c['bold']}📊 System Performance:{self.c['nc']}")
        stats = self.health_manager.get_system_stats()
        if stats:
            print(f"CPU Usage: {stats.get('cpu_percent', 0):.1f}%")
            if 'memory' in stats:
                mem = stats['memory']
                print(f"Memory: {mem.get('used_gb', 0):.1f}GB / {mem.get('total_gb', 0):.1f}GB ({mem.get('percent', 0):.1f}%)")
            if 'disk' in stats:
                disk = stats['disk']
                print(f"Disk (/volume2): {disk.get('used_gb', 0):.1f}GB / {disk.get('total_gb', 0):.1f}GB ({disk.get('percent', 0):.1f}%)")
            
            uptime_hours = stats.get('uptime', 0) / 3600
            print(f"Uptime: {uptime_hours:.1f} hours")
        
        # Redis Cache Status
        print(f"\n{self.c['bold']}🗄️ Cache Performance:{self.c['nc']}")
        cache_stats = self.health_manager.check_redis_cache()
        if cache_stats.get('connected'):
            print(f"✅ Redis: Connected")
            print(f"   └─ Memory Usage: {cache_stats.get('memory_usage', 'Unknown')}")
            print(f"   └─ Hit Rate: {cache_stats.get('hit_rate', 0):.1f}%")
            print(f"   └─ Connected Clients: {cache_stats.get('connected_clients', 0)}")
        else:
            print(f"❌ Redis: {cache_stats.get('error', 'Not connected')}")

    def service_management(self):
        """Service management interface."""
        self._print_header()
        print("--- Service Management ---")
        
        while True:
            print(f"\n{self.c['bold']}Available Services:{self.c['nc']}")
            services = list(self.health_manager.services.keys())
            for i, service in enumerate(services, 1):
                status = self.health_manager.get_service_status(service)
                health_icon = "✅" if status['healthy'] else "❌"
                print(f"{i}. {health_icon} {service.title()}")
            
            print(f"\n{self.c['bold']}Actions:{self.c['nc']}")
            print("R. Restart All Services")
            print("S. Show Detailed Status")
            print("O. Apply System Optimizations")
            print("Q. Return to Main Menu")
            
            choice = self._get_input("Enter choice").upper()
            
            if choice == 'Q':
                break
            elif choice == 'R':
                print(f"\n{self.c['yellow']}Restarting all services...{self.c['nc']}")
                for service in services:
                    success, message = self.health_manager.restart_service(service)
                    status_icon = "✅" if success else "❌"
                    print(f"{status_icon} {service.title()}: {message}")
            elif choice == 'S':
                self.system_health_status()
                input(f"\n{self.c['cyan']}Press Enter to continue...{self.c['nc']}")
            elif choice == 'O':
                print(f"\n{self.c['yellow']}Applying system optimizations...{self.c['nc']}")
                optimizations = self.health_manager.optimize_system()
                for opt in optimizations:
                    print(f"  {opt}")
            elif choice.isdigit():
                service_idx = int(choice) - 1
                if 0 <= service_idx < len(services):
                    service = services[service_idx]
                    print(f"\n{self.c['yellow']}Restarting {service.title()}...{self.c['nc']}")
                    success, message = self.health_manager.restart_service(service)
                    status_icon = "✅" if success else "❌"
                    print(f"{status_icon} {message}")

    def system_backup_restore(self):
        """Enhanced backup and restore for entire system configuration."""
        self._print_header()
        print("--- System Backup & Restore ---")
        print("\n1. Backup IPTV Configuration")
        print("2. Backup System Configuration (Docker, SSL, etc.)")
        print("3. Restore IPTV Configuration")
        print("4. Restore System Configuration")
        print("5. Create Full System Backup")
        print("6. Return to Main Menu")
        
        choice = self._get_input("Enter choice")
        
        if choice == '1':
            self.backup_restore_config()  # Existing IPTV config backup
        elif choice == '2':
            self._backup_system_config()
        elif choice == '3':
            self.backup_restore_config()  # Existing IPTV config restore
        elif choice == '4':
            self._restore_system_config()
        elif choice == '5':
            self._create_full_backup()
        elif choice == '6':
            return
    
    def _backup_system_config(self):
        """Backup Docker configurations, SSL certs, and system settings."""
        backup_dir = f"/volume2/jellyfin-enhanced/backups/system-{int(time.time())}"
        try:
            os.makedirs(backup_dir, exist_ok=True)
            
            # Backup paths to include
            backup_paths = [
                '/volume2/jellyfin-enhanced/nginx',
                '/volume2/jellyfin-enhanced/ssl',
                '/volume2/jellyfin-enhanced/threadfin/config',
                '/volume2/jellyfin-enhanced/iptv-proxy/config'
            ]
            
            for path in backup_paths:
                if os.path.exists(path):
                    dest = os.path.join(backup_dir, os.path.basename(path))
                    shutil.copytree(path, dest, ignore_errors=True)
                    print(f"✅ Backed up: {path}")
                else:
                    print(f"⚠️  Path not found: {path}")
            
            # Backup Docker compose files if they exist
            compose_files = ['/volume2/jellyfin-enhanced/docker-compose.yml']
            for compose_file in compose_files:
                if os.path.exists(compose_file):
                    shutil.copy2(compose_file, backup_dir)
                    print(f"✅ Backed up: {compose_file}")
            
            print(f"{self.c['green']}System configuration backed up to: {backup_dir}{self.c['nc']}")
            
        except Exception as e:
            print(f"{self.c['red']}Backup failed: {e}{self.c['nc']}")
    
    def _create_full_backup(self):
        """Create a complete system backup including all configurations."""
        timestamp = int(time.time())
        backup_name = f"jellyfin-enhanced-full-backup-{timestamp}.tar.gz"
        backup_path = f"/volume2/backups/{backup_name}"
        
        try:
            os.makedirs("/volume2/backups", exist_ok=True)
            
            print(f"{self.c['yellow']}Creating full system backup...{self.c['nc']}")
            
            # Create comprehensive backup
            subprocess.run([
                'tar', '-czf', backup_path,
                '-C', '/volume2',
                'jellyfin-enhanced',
                '--exclude=jellyfin-enhanced/cache',
                '--exclude=jellyfin-enhanced/logs/*.log'
            ], check=True)
            
            # Get backup size
            size_mb = os.path.getsize(backup_path) / (1024 * 1024)
            
            print(f"{self.c['green']}Full backup created: {backup_path}{self.c['nc']}")
            print(f"Backup size: {size_mb:.1f} MB")
            
        except Exception as e:
            print(f"{self.c['red']}Full backup failed: {e}{self.c['nc']}")

    def start_async_monitoring(self):
        """Start async failover monitoring in background."""
        self._print_header()
        print("--- Async Failover Monitoring ---")
        print(f"{self.c['yellow']}Starting enterprise-grade failover monitoring...{self.c['nc']}")
        
        if not asyncio:
            print(f"{self.c['red']}❌ asyncio not available. Advanced monitoring requires Python 3.7+{self.c['nc']}")
            return
            
        try:
            print(f"\n{self.c['bold']}Monitored Services:{self.c['nc']}")
            for service_name, config in self.failover_manager.services.items():
                critical_status = "Critical" if config['critical'] else "Non-Critical"
                print(f"  • {service_name.title()}: {config['url']} ({critical_status})")
            
            print(f"\n{self.c['bold']}Monitoring Configuration:{self.c['nc']}")
            print(f"  • Check Interval: {self.failover_manager.check_interval} seconds")
            print(f"  • Failure Threshold: {self.failover_manager.max_failures} failures")
            print(f"  • Auto-Restart: Enabled for all services")
            
            confirm = self._get_input(f"\n{self.c['cyan']}Start async monitoring? (y/n){self.c['nc']}", "y")
            
            if confirm.lower() == 'y':
                print(f"\n{self.c['green']}Starting async failover monitoring...{self.c['nc']}")
                print(f"{self.c['yellow']}Note: This will run in the background. Use Ctrl+C to stop.{self.c['nc']}")
                
                # Run the async monitoring
                try:
                    asyncio.run(self.failover_manager.start_failover_monitoring())
                except KeyboardInterrupt:
                    print(f"\n{self.c['yellow']}Monitoring stopped by user.{self.c['nc']}")
                    self.failover_manager.stop_monitoring()
                except Exception as e:
                    print(f"\n{self.c['red']}Monitoring error: {e}{self.c['nc']}")
            else:
                print(f"{self.c['yellow']}Async monitoring cancelled.{self.c['nc']}")
                
        except ImportError:
            print(f"{self.c['red']}Error: asyncio not available. Please ensure Python 3.7+ is installed.{self.c['nc']}")
        except Exception as e:
            print(f"{self.c['red']}Failed to start async monitoring: {e}{self.c['nc']}")

    def start_web_viewer(self):
        """Start the built-in web-based multichannel viewer."""
        self._print_header()
        print("--- Web-Based Multichannel Viewer ---")
        
        if not FLASK_AVAILABLE:
            print(f"{self.c['red']}❌ Flask is required for the web viewer.{self.c['nc']}")
            print(f"{self.c['yellow']}Install with: pip install flask{self.c['nc']}")
            return
        
        # Check if channels are available
        channels = self.web_viewer.get_live_channels()
        if not channels:
            print(f"{self.c['yellow']}⚠️  No live channels found.{self.c['nc']}")
            print("Please run an update first (option 12 or 13) to generate channel data.")
            return
        
        print(f"Found {len(channels)} live channels available for viewing.")
        print(f"{self.c['cyan']}Starting web server...{self.c['nc']}")
        
        # Check if already running first
        if self.web_viewer.is_running:
            current_port = getattr(self.web_viewer, 'current_port', WEB_PORT)
            print(f"\n{self.c['yellow']}Web viewer is already running on port {current_port}{self.c['nc']}")
            choice = self._get_input("Stop the current instance? (y/N)", "n").lower()
            if choice == 'y':
                self.web_viewer.stop_server()
                time.sleep(1)
            else:
                return
        
        # Get port preference
        port = WEB_PORT
        port_input = self._get_input(f"Web server port", str(port))
        try:
            port = int(port_input)
            if port < 1024 or port > 65535:
                print(f"{self.c['yellow']}⚠️  Port must be between 1024-65535. Using default {WEB_PORT}.{self.c['nc']}")
                port = WEB_PORT
        except ValueError:
            print(f"{self.c['yellow']}⚠️  Invalid port number. Using default {WEB_PORT}.{self.c['nc']}")
            port = WEB_PORT
        
        # Check if port is available
        if self._is_port_in_use(port):
            print(f"{self.c['red']}❌ Port {port} is already in use.{self.c['nc']}")
            print("Please choose a different port or stop the service using that port.")
            return
        
        if self.web_viewer.start_server(port):
            print(f"\n{self.c['green']}✅ Web viewer started successfully!{self.c['nc']}")
            print(f"{self.c['bold']}Access URLs:{self.c['nc']}")
            print(f"  • Local: {self.c['cyan']}http://localhost:{port}{self.c['nc']}")
            
            # Try to get actual network IP
            try:
                hostname = socket.gethostname()
                local_ip = socket.gethostbyname(hostname)
                print(f"  • Network: {self.c['cyan']}http://{local_ip}:{port}{self.c['nc']}")
            except:
                print(f"  • Network: {self.c['cyan']}http://YOUR_NAS_IP:{port}{self.c['nc']}")
            
            print(f"\n{self.c['yellow']}Features:{self.c['nc']}")
            print("  • Grid layouts: Single, 2x1, 2x2, 3x2, 3x3")
            print("  • Channel selection from dropdown or list")
            print("  • Built-in stream proxy for CORS handling")
            print("  • HLS.js for professional streaming quality")
            print("  • Responsive design for mobile/tablet")
            print(f"\n{self.c['magenta']}The web server will run in the background.{self.c['nc']}")
            print("You can continue using this menu while the web viewer is active.")
        else:
            print(f"{self.c['red']}❌ Failed to start web viewer.{self.c['nc']}")
            print("Check if the port is available or try a different port number.")

    def _exit_program(self):
        """Clean exit with resource cleanup."""
        print(f"\n{self.c['yellow']}Shutting down...{self.c['nc']}")
        
        # Stop web viewer if running
        if hasattr(self, 'web_viewer') and self.web_viewer.is_running:
            print("Stopping web viewer...")
            self.web_viewer.stop_server()
            
        # Stop async monitoring if running
        if hasattr(self, 'failover_manager') and self.failover_manager.running:
            print("Stopping failover monitoring...")
            self.failover_manager.stop_monitoring()
            
        print("Goodbye!")
        sys.exit(0)

    def run(self):
        """Main menu loop."""
        actions = {
            '1': self.run_setup,
            '2': self.list_providers,
            '3': self.toggle_provider,
            '4': self.manage_filters,
            '5': self.manage_epg_sources,
            '6': self.manage_channel_mappings,
            '7': self.manage_proxy_settings,
            '8': self.system_health_status,
            '9': self.service_management,
            '10': self.system_backup_restore,
            '11': self.start_async_monitoring,
            '12': lambda: self.converter.run_update(),
            '13': lambda: self.converter.run_update(force=True),
            '14': lambda: self.converter.run_update(dry_run=True),
            '15': self.setup_cron,
            '16': self.start_web_viewer,
            '17': self.stop_web_viewer,
            '0': self._exit_program
        }

        while True:
            self._print_header()
            print("1. Initial Setup / Add Providers")
            print("2. List Providers")
            print("3. Enable/Disable a Provider")
            print("4. Manage Group Filters")
            print("5. Manage EPG Sources")
            print("6. Advanced Channel Mapping")
            print("7. Manage Proxy Settings")
            print("8. System Health & Performance")
            print("9. Service Management")
            print("10. System Backup & Restore")
            print("11. Start Async Failover Monitoring")
            print("12. Run Update Now")
            print("13. Run Update (force refresh)")
            print("14. Dry Run (simulate and report)")
            print("15. Setup Cron Automation")
            print(f"16. {self.c['bold']}🌐 Start Web Multichannel Viewer{self.c['nc']} {'(Running)' if self.web_viewer.is_running else ''}")
            if self.web_viewer.is_running:
                print(f"17. {self.c['bold']}🛑 Stop Web Viewer{self.c['nc']}")
            print("0. Exit")
            
            choice = self._get_input("\nEnter your choice")
            action = actions.get(choice)
            if action:
                # For methods moved to converter, they need access to UI elements if they use them
                # A better design would be for the manager to get data and pass it to the converter
                # For now, we call them directly, assuming they are self-contained
                action()

                if choice != '0':
                    self._get_input("\nPress Enter to return to the menu...")
            else:
                print(f"{self.c['red']}Invalid choice. Please try again.{self.c['nc']}")
                time.sleep(1)

# --- Main Execution ---
def main():
    """Main entry point. Handles command-line arguments or starts the menu."""
    parser = argparse.ArgumentParser(
        description='Multi-Provider IPTV to STRM Converter & Manager.',
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument('--auto-mode', action='store_true', help='Run update automatically using saved config.')
    parser.add_argument('--force', action='store_true', help='Force update even if no remote changes are detected.')
    parser.add_argument('--dry-run', action='store_true', help='Simulate an update and show stats without creating files.')
    parser.add_argument('--schedule', choices=['6h', '12h', '24h'], help='Run in a continuous loop with a given schedule.')
    
    args = parser.parse_args()
    
    converter = MultiProviderM3UConverter()

    if args.schedule:
        intervals = {'6h': 6*3600, '12h': 12*3600, '24h': 24*3600}
        interval = intervals[args.schedule]
        logger.info(f"Starting scheduler mode: updating every {args.schedule}")
        while True:
            try:
                converter.run_update(force=args.force)
            except Exception as e:
                logger.error(f"Scheduled update failed: {e}", exc_info=True)
            logger.info(f"Next update in {args.schedule}. Sleeping...")
            time.sleep(interval)
    
    elif args.auto_mode or args.force or args.dry_run:
        converter.run_update(force=args.force, dry_run=args.dry_run)
    
    else:
        # No arguments provided, start the interactive menu
        manager = IPTVManager()
        manager.run()

# --- Web-Based Multichannel Viewer ---
class WebViewer:
    """Built-in web-based multichannel viewer for IPTV streams."""
    
    def __init__(self, converter):
        self.converter = converter
        self.app = None
        self.server_thread = None
        self.server_instance = None
        self.is_running = False
        
    def get_live_channels(self):
        """Extract live channels from generated playlists."""
        channels = []
        
        # Look for generated M3U files
        live_m3u_path = os.path.join(self.converter.base_dir, "IPV-Live_EPG.m3u")
        if not os.path.exists(live_m3u_path):
            logger.warning(f"M3U file not found: {live_m3u_path}")
            # Try alternative paths
            alt_paths = [
                os.path.join(self.converter.base_dir, "merged_playlist.m3u"),
                os.path.join(self.converter.base_dir, "playlist.m3u")
            ]
            for alt_path in alt_paths:
                if os.path.exists(alt_path):
                    live_m3u_path = alt_path
                    logger.info(f"Using alternative M3U file: {alt_path}")
                    break
            else:
                return channels
            
        try:
            with open(live_m3u_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                
            if not content.strip():
                logger.warning("M3U file is empty")
                return channels
                
            # Parse M3U content
            lines = content.split('\n')
            current_channel = {}
            
            for line_num, line in enumerate(lines, 1):
                line = line.strip()
                if not line or line.startswith('#') and not line.startswith('#EXTINF:'):
                    continue
                    
                try:
                    if line.startswith('#EXTINF:'):
                        # Reset channel data
                        current_channel = {}
                        
                        # Extract channel info with better regex
                        if 'tvg-name=' in line:
                            name_match = re.search(r'tvg-name="([^"]*)"', line)
                            if name_match:
                                current_channel['name'] = name_match.group(1).strip()
                        
                        if 'group-title=' in line:
                            group_match = re.search(r'group-title="([^"]*)"', line)
                            if group_match:
                                current_channel['group'] = group_match.group(1).strip()
                        
                        # Extract display name from the end of the line
                        if ',' in line:
                            display_name = line.split(',')[-1].strip()
                            if display_name and not current_channel.get('name'):
                                current_channel['name'] = display_name
                                
                    elif line.startswith(('http://', 'https://')) and current_channel:
                        # Validate URL format
                        if self._is_valid_stream_url(line):
                            current_channel['url'] = line
                            current_channel['id'] = hashlib.md5(line.encode()).hexdigest()[:8]
                            
                            # Ensure we have a name
                            if not current_channel.get('name'):
                                current_channel['name'] = f"Channel {len(channels) + 1}"
                            
                            # Add default group if missing
                            if not current_channel.get('group'):
                                current_channel['group'] = 'General'
                            
                            channels.append(current_channel.copy())
                            current_channel = {}
                        
                except Exception as line_error:
                    logger.warning(f"Error parsing line {line_num}: {line_error}")
                    continue
                        
        except (IOError, UnicodeDecodeError) as e:
            logger.error(f"Error reading M3U file: {e}")
        except Exception as e:
            logger.error(f"Unexpected error parsing M3U file: {e}")
                
        logger.info(f"Loaded {len(channels)} channels from M3U file")
        return channels
    
    def create_app(self):
        """Create Flask web application."""
        if not FLASK_AVAILABLE:
            return None
            
        app = Flask(__name__)
        app.logger.disabled = True  # Disable Flask logging
        
        @app.route('/')
        def index():
            channels = self.get_live_channels()
            return render_template_string(WEB_VIEWER_TEMPLATE, channels=channels)
        
        @app.route('/api/channels')
        def api_channels():
            return jsonify(self.get_live_channels())
        
        @app.route('/proxy/<path:url>')
        def proxy_stream(url):
            """Proxy IPTV streams to handle CORS issues."""
            try:
                # Basic URL validation
                if not url.startswith(('http://', 'https://')):
                    return "Invalid URL format", 400
                
                # Set headers for streaming
                headers = {
                    'User-Agent': 'Mozilla/5.0 (compatible; IPTV-Viewer/1.0)',
                    'Accept': '*/*',
                    'Connection': 'keep-alive'
                }
                
                response = requests.get(url, stream=True, timeout=15, headers=headers, 
                                      allow_redirects=True, verify=False)
                response.raise_for_status()
                
                def generate():
                    try:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                yield chunk
                    except Exception as stream_error:
                        logger.error(f"Stream error for {url}: {stream_error}")
                        yield b''  # End stream gracefully
                
                # Determine content type
                content_type = response.headers.get('content-type', 'video/mp2t')
                if 'm3u8' in url.lower():
                    content_type = 'application/vnd.apple.mpegurl'
                elif 'ts' in url.lower():
                    content_type = 'video/mp2t'
                
                flask_response = app.response_class(generate(), mimetype=content_type)
                flask_response.headers['Access-Control-Allow-Origin'] = '*'
                flask_response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
                flask_response.headers['Access-Control-Allow-Headers'] = '*'
                flask_response.headers['Cache-Control'] = 'no-cache'
                
                return flask_response
                
            except requests.exceptions.Timeout:
                return "Stream timeout", 504
            except requests.exceptions.ConnectionError:
                return "Connection failed", 503
            except requests.exceptions.HTTPError as e:
                return f"HTTP error: {e.response.status_code}", e.response.status_code
            except Exception as e:
                logger.error(f"Proxy error for {url}: {e}")
                return f"Stream error: {str(e)[:100]}", 500
        
        @app.route('/WebViewerControl/<action>', methods=['POST'])
        def control_viewer(action):
            """API endpoint for Jellyfin plugin to control web viewer."""
            try:
                if action == 'start':
                    if self.is_running:
                        return jsonify({
                            'status': 'success', 
                            'message': 'Web viewer is already running', 
                            'port': port,
                            'channels': len(self.get_live_channels())
                        })
                    else:
                        return jsonify({'status': 'error', 'message': 'Web viewer not running'}), 503
                        
                elif action == 'stop':
                    return jsonify({
                        'status': 'success', 
                        'message': 'Stop command received - server will continue running'
                    })
                    
                elif action == 'status':
                    return jsonify({
                        'status': 'success',
                        'running': self.is_running,
                        'port': port if self.is_running else None,
                        'channels': len(self.get_live_channels()) if self.is_running else 0
                    })
                    
                else:
                    return jsonify({'status': 'error', 'message': f'Unknown action: {action}'}), 400
                    
            except Exception as e:
                logger.error(f"Control API error: {e}")
                return jsonify({'status': 'error', 'message': str(e)}), 500
        
        return app
    
    def start_server(self, port=WEB_PORT):
        """Start the web server in a separate thread."""
        if not FLASK_AVAILABLE:
            print("❌ Flask not available. Install with: pip install flask")
            return False
        
        if self.is_running:
            print(f"⚠️  Web viewer is already running on port {port}")
            return True
            
        # Check if port is available
        if not self._is_port_available(port):
            print(f"❌ Port {port} is already in use")
            return False
        
        self.app = self.create_app()
        if not self.app:
            return False
        
        def run_server():
            try:
                self.is_running = True
                # Suppress Flask startup messages
                log = logging.getLogger('werkzeug')
                log.setLevel(logging.ERROR)
                
                self.app.run(host='0.0.0.0', port=port, debug=False, 
                           use_reloader=False, threaded=True)
            except Exception as e:
                logger.error(f"Server error: {e}")
            finally:
                self.is_running = False
        
        self.current_port = port
        self.server_thread = threading.Thread(target=run_server, daemon=True)
        self.server_thread.start()
        
        # Wait for server to start
        for _ in range(10):  # Wait up to 5 seconds
            time.sleep(0.5)
            if self.is_running:
                break
        
        return self.is_running
    
    def _is_valid_stream_url(self, url):
        """Validate if URL is a valid streaming URL."""
        if not url or len(url) < 10:
            return False
        
        # Check for valid URL format
        if not url.startswith(('http://', 'https://')):
            return False
            
        # Check for common streaming patterns
        valid_extensions = ('.m3u8', '.ts', '.mp4', '.mkv', '.avi')
        valid_patterns = ['playlist', 'stream', 'live', 'channel']
        
        url_lower = url.lower()
        return (any(ext in url_lower for ext in valid_extensions) or 
                any(pattern in url_lower for pattern in valid_patterns) or
                '.' in url.split('/')[-1])
    
    def _is_port_available(self, port):
        """Check if a port is available for use."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('localhost', port))
                return True
        except OSError:
            return False
    
    def _is_port_in_use(self, port):
        """Check if a port is currently in use."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                result = s.connect_ex(('localhost', port))
                return result == 0
        except:
            return False
    
    def stop_server(self):
        """Stop the web server."""
        if self.is_running:
            self.is_running = False
            self.current_port = None
            return True
        return False

# HTML Template for Web Viewer
WEB_VIEWER_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>IPTV Multichannel Viewer</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: Arial, sans-serif; 
            background: #1a1a1a; 
            color: white; 
            overflow-x: hidden;
        }
        .header {
            background: #2d2d2d;
            padding: 15px;
            text-align: center;
            border-bottom: 2px solid #444;
        }
        .controls {
            background: #333;
            padding: 10px;
            display: flex;
            justify-content: center;
            gap: 10px;
            flex-wrap: wrap;
        }
        .btn {
            background: #007bff;
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
        }
        .btn:hover { background: #0056b3; }
        .btn.active { background: #28a745; }
        .grid-container {
            display: grid;
            gap: 10px;
            padding: 10px;
            height: calc(100vh - 120px);
        }
        .grid-1 { grid-template-columns: 1fr; }
        .grid-2 { grid-template-columns: 1fr 1fr; }
        .grid-4 { grid-template-columns: 1fr 1fr; grid-template-rows: 1fr 1fr; }
        .grid-6 { grid-template-columns: 1fr 1fr 1fr; grid-template-rows: 1fr 1fr; }
        .grid-9 { grid-template-columns: 1fr 1fr 1fr; grid-template-rows: 1fr 1fr 1fr; }
        .channel-slot {
            background: #2d2d2d;
            border: 2px solid #444;
            border-radius: 8px;
            position: relative;
            overflow: hidden;
            min-height: 200px;
        }
        .channel-slot.active { border-color: #007bff; }
        .channel-info {
            position: absolute;
            top: 5px;
            left: 5px;
            background: rgba(0,0,0,0.7);
            padding: 5px 10px;
            border-radius: 4px;
            font-size: 12px;
            z-index: 10;
        }
        .channel-selector {
            position: absolute;
            bottom: 5px;
            left: 5px;
            right: 5px;
            z-index: 10;
        }
        .channel-selector select {
            width: 100%;
            background: #444;
            color: white;
            border: 1px solid #666;
            padding: 5px;
            border-radius: 4px;
        }
        video {
            width: 100%;
            height: 100%;
            object-fit: cover;
            background: #000;
        }
        .video-container {
            position: relative;
            width: 100%;
            height: 100%;
        }
        .video-overlay {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            color: white;
            background: rgba(0,0,0,0.7);
            padding: 10px;
            border-radius: 4px;
            display: none;
        }
        .placeholder {
            display: flex;
            align-items: center;
            justify-content: center;
            height: 100%;
            color: #888;
            font-size: 18px;
        }
        .channel-list {
            max-height: 300px;
            overflow-y: auto;
            background: #2d2d2d;
            border: 1px solid #444;
            border-radius: 4px;
            margin: 10px;
        }
        .channel-item {
            padding: 10px;
            border-bottom: 1px solid #444;
            cursor: pointer;
            display: flex;
            justify-content: space-between;
        }
        .channel-item:hover { background: #444; }
        .channel-group { color: #888; font-size: 12px; }
    </style>
    <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
</head>
<body>
    <div class="header">
        <h1>🔴 IPTV Multichannel Viewer</h1>
        <p>Select channels below to view in grid layout</p>
    </div>
    
    <div class="controls">
        <button class="btn grid-btn active" data-grid="1">Single</button>
        <button class="btn grid-btn" data-grid="2">2x1</button>
        <button class="btn grid-btn" data-grid="4">2x2</button>
        <button class="btn grid-btn" data-grid="6">3x2</button>
        <button class="btn grid-btn" data-grid="9">3x3</button>
        <button class="btn" onclick="stopAll()">Stop All</button>
        <button class="btn" onclick="toggleChannelList()">Channel List</button>
    </div>
    
    <div id="channelList" class="channel-list" style="display: none;">
        {% for channel in channels %}
        <div class="channel-item" onclick="addToGrid('{{ channel.url }}', '{{ channel.name }}', '{{ channel.group or '' }}')">
            <span>{{ channel.name }}</span>
            <span class="channel-group">{{ channel.group or 'General' }}</span>
        </div>
        {% endfor %}
    </div>
    
    <div id="gridContainer" class="grid-container grid-1">
        <!-- Grid slots will be generated by JavaScript -->
    </div>

    <script>
        let currentGrid = 1;
        let channels = {{ channels | tojson }};
        let activeSlots = {};
        
        function initGrid() {
            updateGrid(currentGrid);
        }
        
        function updateGrid(gridSize) {
            currentGrid = gridSize;
            const container = document.getElementById('gridContainer');
            container.className = `grid-container grid-${gridSize}`;
            container.innerHTML = '';
            
            // Update button states
            document.querySelectorAll('.grid-btn').forEach(btn => {
                btn.classList.remove('active');
                if (btn.dataset.grid == gridSize) {
                    btn.classList.add('active');
                }
            });
            
            // Create slots
            for (let i = 0; i < gridSize; i++) {
                const slot = document.createElement('div');
                slot.className = 'channel-slot';
                slot.id = `slot-${i}`;
                
                slot.innerHTML = `
                    <div class="channel-info" id="info-${i}">Slot ${i + 1}</div>
                    <div class="placeholder" id="placeholder-${i}">
                        Click "Channel List" to select a channel
                    </div>
                    <div class="channel-selector">
                        <select onchange="changeChannel(${i}, this.value)">
                            <option value="">Select Channel...</option>
                            ${channels.map(ch => `<option value="${ch.url}">${ch.name} (${ch.group || 'General'})</option>`).join('')}
                        </select>
                    </div>
                `;
                
                container.appendChild(slot);
            }
        }
        
        function changeChannel(slotId, url) {
            if (!url) {
                stopChannel(slotId);
                return;
            }
            
            const channel = channels.find(ch => ch.url === url);
            if (channel) {
                loadChannel(slotId, url, channel.name, channel.group || 'General');
            }
        }
        
        function loadChannel(slotId, url, name, group) {
            const slot = document.getElementById(`slot-${slotId}`);
            const info = document.getElementById(`info-${slotId}`);
            const placeholder = document.getElementById(`placeholder-${slotId}`);
            
            // Stop existing video and HLS instance
            const existingVideo = slot.querySelector('video');
            if (existingVideo && existingVideo.hls) {
                existingVideo.hls.destroy();
            }
            if (existingVideo) {
                existingVideo.remove();
            }
            
            // Update info
            info.textContent = `${name} (${group})`;
            placeholder.style.display = 'flex';
            placeholder.textContent = 'Loading...';
            
            // Create video container
            const videoContainer = document.createElement('div');
            videoContainer.className = 'video-container';
            
            // Create video element
            const video = document.createElement('video');
            video.controls = true;
            video.autoplay = true;
            video.muted = true; // Required for autoplay
            video.style.width = '100%';
            video.style.height = '100%';
            video.style.objectFit = 'cover';
            video.crossOrigin = 'anonymous';
            
            // Create overlay for status messages
            const overlay = document.createElement('div');
            overlay.className = 'video-overlay';
            overlay.textContent = 'Connecting...';
            
            videoContainer.appendChild(video);
            videoContainer.appendChild(overlay);
            
            // Enhanced error handling
            video.onerror = function(e) {
                placeholder.style.display = 'flex';
                placeholder.textContent = 'Stream Error';
                overlay.style.display = 'block';
                overlay.textContent = 'Connection failed';
                console.error('Video load error for:', url, e);
            };
            
            video.onloadstart = function() {
                overlay.style.display = 'block';
                overlay.textContent = 'Buffering...';
            };
            
            video.oncanplay = function() {
                placeholder.style.display = 'none';
                overlay.style.display = 'none';
            };
            
            video.onwaiting = function() {
                overlay.style.display = 'block';
                overlay.textContent = 'Buffering...';
            };
            
            video.onplaying = function() {
                overlay.style.display = 'none';
            };
            
            // Use HLS.js for better compatibility (ExoPlayer-like functionality)
            const proxyUrl = `/proxy/${encodeURIComponent(url)}`;
            
            if (Hls.isSupported()) {
                const hls = new Hls({
                    enableWorker: true,
                    lowLatencyMode: true,
                    backBufferLength: 90
                });
                
                hls.loadSource(proxyUrl);
                hls.attachMedia(video);
                
                hls.on(Hls.Events.MANIFEST_PARSED, function() {
                    console.log('HLS manifest loaded for:', name);
                    video.play().catch(e => console.log('Autoplay prevented:', e));
                });
                
                hls.on(Hls.Events.ERROR, function(event, data) {
                    console.error('HLS error:', data);
                    if (data.fatal) {
                        placeholder.style.display = 'flex';
                        placeholder.textContent = 'Stream Error';
                        overlay.style.display = 'block';
                        overlay.textContent = 'HLS Error: ' + data.type;
                    }
                });
                
                video.hls = hls; // Store reference for cleanup
            } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
                // Native HLS support (Safari, etc.)
                video.src = proxyUrl;
                video.play().catch(e => console.log('Autoplay prevented:', e));
            } else {
                // Fallback to direct stream
                video.src = proxyUrl;
                video.play().catch(e => console.log('Autoplay prevented:', e));
            }
            
            slot.appendChild(videoContainer);
            slot.classList.add('active');
            activeSlots[slotId] = { url, name, group, hls: video.hls };
        }
        
        function stopChannel(slotId) {
            const slot = document.getElementById(`slot-${slotId}`);
            const videoContainer = slot.querySelector('.video-container');
            const video = slot.querySelector('video');
            const placeholder = document.getElementById(`placeholder-${slotId}`);
            
            // Clean up HLS instance
            if (video && video.hls) {
                video.hls.destroy();
            }
            
            if (videoContainer) {
                videoContainer.remove();
            } else if (video) {
                video.remove();
            }
            
            placeholder.style.display = 'flex';
            placeholder.textContent = 'Select a channel';
            slot.classList.remove('active');
            delete activeSlots[slotId];
        }
        
        function stopAll() {
            Object.keys(activeSlots).forEach(slotId => {
                stopChannel(parseInt(slotId));
            });
        }
        
        function addToGrid(url, name, group) {
            // Find first empty slot
            for (let i = 0; i < currentGrid; i++) {
                if (!activeSlots[i]) {
                    loadChannel(i, url, name, group);
                    // Update selector
                    const select = document.querySelector(`#slot-${i} select`);
                    select.value = url;
                    break;
                }
            }
            toggleChannelList(); // Hide list after selection
        }
        
        function toggleChannelList() {
            const list = document.getElementById('channelList');
            list.style.display = list.style.display === 'none' ? 'block' : 'none';
        }
        
        // Grid button handlers
        document.querySelectorAll('.grid-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                updateGrid(parseInt(btn.dataset.grid));
            });
        });
        
        // Initialize
        initGrid();
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
