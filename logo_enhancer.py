#!/usr/bin/env python3
"""
Logo Enhancement System for Jellyfin IPTV Manager
Automatically fetches high-quality transparent logos from GitHub repositories
"""

import os
import re
import json
import asyncio
import aiohttp
import logging
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse, quote
from pathlib import Path
import hashlib

logger = logging.getLogger(__name__)

class LogoEnhancer:
    """Enhanced logo fetching and management system"""
    
    def __init__(self, cache_dir: str = "logos_cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        
        # GitHub logo repositories
        self.logo_sources = [
            {
                "name": "tv-logos",
                "base_url": "https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries",
                "countries": ["us", "uk", "ca", "de", "fr", "it", "es", "nl", "be", "pt"]
            },
            {
                "name": "iptv-logos", 
                "base_url": "https://raw.githubusercontent.com/iptv-org/logos/master/logos",
                "format": "png"
            },
            {
                "name": "picons",
                "base_url": "https://raw.githubusercontent.com/picons/picons/master/build-source/logos",
                "format": "png"
            }
        ]
        
        # Logo cache and mapping
        self.logo_cache = {}
        self.channel_mappings = {}
        self.load_cache()
        
    def load_cache(self):
        """Load logo cache from disk"""
        cache_file = self.cache_dir / "logo_cache.json"
        if cache_file.exists():
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.logo_cache = data.get('cache', {})
                    self.channel_mappings = data.get('mappings', {})
                logger.info(f"Loaded {len(self.logo_cache)} cached logos")
            except Exception as e:
                logger.error(f"Failed to load logo cache: {e}")
    
    def save_cache(self):
        """Save logo cache to disk"""
        cache_file = self.cache_dir / "logo_cache.json"
        try:
            data = {
                'cache': self.logo_cache,
                'mappings': self.channel_mappings,
                'version': '1.0'
            }
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.debug("Logo cache saved")
        except Exception as e:
            logger.error(f"Failed to save logo cache: {e}")
    
    def normalize_channel_name(self, name: str) -> str:
        """Normalize channel name for logo matching"""
        # Remove common suffixes and prefixes
        normalized = re.sub(r'\s*(HD|4K|UHD|FHD|SD|HQ)\s*', '', name, flags=re.IGNORECASE)
        normalized = re.sub(r'\s*(TV|Channel|Ch\.?)\s*$', '', normalized, flags=re.IGNORECASE)
        
        # Remove special characters and extra spaces
        normalized = re.sub(r'[^\w\s]', '', normalized)
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        
        return normalized.lower()
    
    def generate_logo_variants(self, channel_name: str) -> List[str]:
        """Generate possible logo filename variants"""
        normalized = self.normalize_channel_name(channel_name)
        variants = []
        
        # Original normalized name
        variants.append(normalized.replace(' ', ''))
        variants.append(normalized.replace(' ', '-'))
        variants.append(normalized.replace(' ', '_'))
        
        # Without spaces
        no_spaces = normalized.replace(' ', '')
        variants.append(no_spaces)
        
        # Common abbreviations
        if 'television' in normalized:
            variants.append(normalized.replace('television', 'tv'))
        if 'network' in normalized:
            variants.append(normalized.replace('network', 'net'))
        
        # Add original name variants
        original = channel_name.lower()
        variants.extend([
            original.replace(' ', ''),
            original.replace(' ', '-'),
            original.replace(' ', '_')
        ])
        
        # Remove duplicates while preserving order
        seen = set()
        unique_variants = []
        for variant in variants:
            if variant not in seen:
                seen.add(variant)
                unique_variants.append(variant)
        
        return unique_variants
    
    async def fetch_logo_from_source(self, session: aiohttp.ClientSession, 
                                   source: Dict, channel_name: str) -> Optional[str]:
        """Fetch logo from a specific source"""
        variants = self.generate_logo_variants(channel_name)
        
        for variant in variants:
            try:
                if source["name"] == "tv-logos":
                    # Try different countries
                    for country in source.get("countries", ["us"]):
                        url = f"{source['base_url']}/{country}/{variant}.png"
                        if await self.check_url_exists(session, url):
                            return url
                else:
                    # Standard logo repositories
                    formats = ["png", "svg", "jpg"]
                    for fmt in formats:
                        url = f"{source['base_url']}/{variant}.{fmt}"
                        if await self.check_url_exists(session, url):
                            return url
                        
                        # Try with uppercase
                        url = f"{source['base_url']}/{variant.upper()}.{fmt}"
                        if await self.check_url_exists(session, url):
                            return url
                            
            except Exception as e:
                logger.debug(f"Error checking logo variant {variant}: {e}")
                continue
        
        return None
    
    async def check_url_exists(self, session: aiohttp.ClientSession, url: str) -> bool:
        """Check if URL exists with HEAD request"""
        try:
            async with session.head(url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                return response.status == 200
        except:
            return False
    
    async def download_logo(self, session: aiohttp.ClientSession, 
                          url: str, channel_name: str) -> Optional[str]:
        """Download logo and save to cache"""
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    content = await response.read()
                    
                    # Generate filename
                    url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
                    ext = Path(urlparse(url).path).suffix or '.png'
                    filename = f"{self.normalize_channel_name(channel_name)}_{url_hash}{ext}"
                    filepath = self.cache_dir / filename
                    
                    # Save file
                    with open(filepath, 'wb') as f:
                        f.write(content)
                    
                    logger.info(f"Downloaded logo for {channel_name}: {filename}")
                    return str(filepath)
                    
        except Exception as e:
            logger.error(f"Failed to download logo from {url}: {e}")
        
        return None
    
    async def enhance_channel_logo(self, channel_name: str, 
                                 existing_logo: Optional[str] = None) -> Optional[str]:
        """Enhance a single channel's logo"""
        
        # Check cache first
        cache_key = self.normalize_channel_name(channel_name)
        if cache_key in self.logo_cache:
            cached_path = self.logo_cache[cache_key]
            if Path(cached_path).exists():
                return cached_path
        
        # If existing logo is high quality, keep it
        if existing_logo and self.is_high_quality_logo(existing_logo):
            self.logo_cache[cache_key] = existing_logo
            return existing_logo
        
        # Search for better logo
        async with aiohttp.ClientSession() as session:
            for source in self.logo_sources:
                logo_url = await self.fetch_logo_from_source(session, source, channel_name)
                if logo_url:
                    # Download and cache
                    local_path = await self.download_logo(session, logo_url, channel_name)
                    if local_path:
                        self.logo_cache[cache_key] = local_path
                        self.save_cache()
                        return local_path
        
        # No enhancement found, cache the existing logo if any
        if existing_logo:
            self.logo_cache[cache_key] = existing_logo
            return existing_logo
        
        return None
    
    def is_high_quality_logo(self, logo_url: str) -> bool:
        """Check if existing logo is already high quality"""
        if not logo_url:
            return False
        
        # Check for known high-quality sources
        high_quality_domains = [
            'github.com',
            'githubusercontent.com',
            'tv-logo.com',
            'iptv-org.github.io'
        ]
        
        parsed = urlparse(logo_url)
        if any(domain in parsed.netloc for domain in high_quality_domains):
            return True
        
        # Check file extension (SVG and PNG are preferred)
        if logo_url.lower().endswith(('.svg', '.png')):
            return True
        
        return False
    
    async def enhance_channel_batch(self, channels: List[Dict]) -> List[Dict]:
        """Enhance logos for a batch of channels"""
        enhanced_channels = []
        
        # Process in batches to avoid overwhelming servers
        batch_size = 5
        for i in range(0, len(channels), batch_size):
            batch = channels[i:i + batch_size]
            tasks = []
            
            for channel in batch:
                task = self.enhance_channel_logo(
                    channel.get('name', ''),
                    channel.get('logo', '')
                )
                tasks.append(task)
            
            # Wait for batch to complete
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Update channels with enhanced logos
            for j, result in enumerate(results):
                channel = batch[j].copy()
                if isinstance(result, str):
                    channel['logo'] = result
                    channel['logo_enhanced'] = True
                elif not isinstance(result, Exception):
                    channel['logo_enhanced'] = False
                
                enhanced_channels.append(channel)
            
            # Small delay between batches
            if i + batch_size < len(channels):
                await asyncio.sleep(1)
        
        logger.info(f"Enhanced logos for {len(enhanced_channels)} channels")
        return enhanced_channels
    
    def add_custom_mapping(self, channel_name: str, logo_url: str):
        """Add custom channel to logo mapping"""
        cache_key = self.normalize_channel_name(channel_name)
        self.channel_mappings[cache_key] = logo_url
        self.save_cache()
        logger.info(f"Added custom mapping: {channel_name} -> {logo_url}")
    
    def remove_custom_mapping(self, channel_name: str) -> bool:
        """Remove custom channel mapping"""
        cache_key = self.normalize_channel_name(channel_name)
        if cache_key in self.channel_mappings:
            del self.channel_mappings[cache_key]
            self.save_cache()
            logger.info(f"Removed custom mapping for: {channel_name}")
            return True
        return False
    
    def get_logo_statistics(self) -> Dict:
        """Get logo enhancement statistics"""
        total_cached = len(self.logo_cache)
        custom_mappings = len(self.channel_mappings)
        
        # Count local vs remote logos
        local_logos = sum(1 for path in self.logo_cache.values() 
                         if not path.startswith('http'))
        remote_logos = total_cached - local_logos
        
        # Calculate cache size
        cache_size = 0
        for filepath in self.logo_cache.values():
            if not filepath.startswith('http'):
                try:
                    cache_size += Path(filepath).stat().st_size
                except:
                    pass
        
        return {
            'total_cached_logos': total_cached,
            'local_logos': local_logos,
            'remote_logos': remote_logos,
            'custom_mappings': custom_mappings,
            'cache_size_mb': cache_size / (1024 * 1024),
            'cache_directory': str(self.cache_dir)
        }
    
    def cleanup_cache(self, max_age_days: int = 30):
        """Clean up old cached logos"""
        import time
        
        current_time = time.time()
        max_age_seconds = max_age_days * 24 * 3600
        cleaned_count = 0
        
        # Clean up files
        for filepath in self.cache_dir.glob('*'):
            if filepath.is_file():
                try:
                    file_age = current_time - filepath.stat().st_mtime
                    if file_age > max_age_seconds:
                        filepath.unlink()
                        cleaned_count += 1
                except:
                    pass
        
        # Clean up cache entries for missing files
        to_remove = []
        for key, path in self.logo_cache.items():
            if not path.startswith('http') and not Path(path).exists():
                to_remove.append(key)
        
        for key in to_remove:
            del self.logo_cache[key]
            cleaned_count += 1
        
        if cleaned_count > 0:
            self.save_cache()
            logger.info(f"Cleaned up {cleaned_count} old logo cache entries")
        
        return cleaned_count

# Integration with IPTV Manager
class IPTVLogoEnhancer:
    """Integration class for IPTV Manager"""
    
    def __init__(self, iptv_manager):
        self.iptv_manager = iptv_manager
        self.logo_enhancer = LogoEnhancer()
    
    async def enhance_provider_logos(self, provider_name: str):
        """Enhance logos for a specific provider"""
        config = self.iptv_manager.load_config()
        providers = config.get('providers', [])
        
        for provider in providers:
            if provider.get('name') == provider_name and provider.get('enabled', True):
                # Get M3U content
                m3u_content = self.iptv_manager.download_m3u(provider_name)
                if not m3u_content:
                    continue
                
                # Parse channels
                parsed_content = self.iptv_manager.parse_m3u_content(
                    m3u_content, provider, {}, {}
                )
                
                # Enhance logos for each category
                for category, channels in parsed_content.items():
                    channel_list = list(channels.values())
                    enhanced_channels = await self.logo_enhancer.enhance_channel_batch(channel_list)
                    
                    # Update the parsed content
                    for enhanced_channel in enhanced_channels:
                        channel_id = enhanced_channel.get('name', '')
                        if channel_id in channels:
                            channels[channel_id].update(enhanced_channel)
                
                logger.info(f"Enhanced logos for provider: {provider_name}")
                break

# Example usage
async def main():
    """Example usage of logo enhancer"""
    enhancer = LogoEnhancer()
    
    # Test channels
    test_channels = [
        {"name": "CNN HD", "logo": ""},
        {"name": "BBC One", "logo": ""},
        {"name": "ESPN", "logo": ""},
        {"name": "Discovery Channel", "logo": ""}
    ]
    
    # Enhance logos
    enhanced = await enhancer.enhance_channel_batch(test_channels)
    
    # Print results
    for channel in enhanced:
        print(f"{channel['name']}: {channel.get('logo', 'No logo found')}")
    
    # Print statistics
    stats = enhancer.get_logo_statistics()
    print(f"\nStatistics: {stats}")

if __name__ == "__main__":
    asyncio.run(main())
