#!/usr/bin/env python3
"""
Stream Health Checker for Jellyfin IPTV Manager
Parallel stream testing and health monitoring with detailed reporting
"""

import asyncio
import aiohttp
import time
import json
import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
import statistics

logger = logging.getLogger(__name__)

@dataclass
class StreamHealth:
    """Stream health status information"""
    url: str
    status: str  # 'online', 'offline', 'timeout', 'error'
    response_time: float = 0.0
    status_code: Optional[int] = None
    content_type: Optional[str] = None
    content_length: Optional[int] = None
    error_message: Optional[str] = None
    timestamp: float = 0.0
    
    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()

@dataclass
class ChannelHealthReport:
    """Health report for a channel with multiple streams"""
    channel_name: str
    channel_id: str
    streams: List[StreamHealth]
    best_stream: Optional[StreamHealth] = None
    worst_stream: Optional[StreamHealth] = None
    average_response_time: float = 0.0
    success_rate: float = 0.0
    
    def __post_init__(self):
        if self.streams:
            online_streams = [s for s in self.streams if s.status == 'online']
            
            if online_streams:
                self.best_stream = min(online_streams, key=lambda x: x.response_time)
                self.worst_stream = max(online_streams, key=lambda x: x.response_time)
                self.average_response_time = statistics.mean(s.response_time for s in online_streams)
            
            self.success_rate = len(online_streams) / len(self.streams) * 100

class StreamHealthChecker:
    """Advanced stream health checking with parallel processing"""
    
    def __init__(self, max_concurrent: int = 10, timeout: int = 10):
        self.max_concurrent = max_concurrent
        self.timeout = timeout
        self.session = None
        self.health_history = {}
        
    async def __aenter__(self):
        connector = aiohttp.TCPConnector(limit=self.max_concurrent, limit_per_host=5)
        timeout = aiohttp.ClientTimeout(total=self.timeout, connect=5)
        self.session = aiohttp.ClientSession(connector=connector, timeout=timeout)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def check_stream_health(self, url: str) -> StreamHealth:
        """Check health of a single stream"""
        start_time = time.time()
        
        try:
            # Validate URL
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                return StreamHealth(
                    url=url,
                    status='error',
                    error_message='Invalid URL format'
                )
            
            # Make HEAD request first (faster)
            async with self.session.head(url) as response:
                response_time = time.time() - start_time
                
                if response.status == 200:
                    return StreamHealth(
                        url=url,
                        status='online',
                        response_time=response_time,
                        status_code=response.status,
                        content_type=response.headers.get('content-type'),
                        content_length=int(response.headers.get('content-length', 0))
                    )
                elif response.status in [301, 302, 307, 308]:
                    # Follow redirect for HEAD requests
                    redirect_url = response.headers.get('location')
                    if redirect_url:
                        return await self.check_stream_health(redirect_url)
                
                return StreamHealth(
                    url=url,
                    status='offline',
                    response_time=response_time,
                    status_code=response.status,
                    error_message=f'HTTP {response.status}'
                )
                
        except asyncio.TimeoutError:
            return StreamHealth(
                url=url,
                status='timeout',
                response_time=self.timeout,
                error_message='Request timeout'
            )
        except aiohttp.ClientError as e:
            return StreamHealth(
                url=url,
                status='error',
                response_time=time.time() - start_time,
                error_message=str(e)
            )
        except Exception as e:
            return StreamHealth(
                url=url,
                status='error',
                response_time=time.time() - start_time,
                error_message=f'Unexpected error: {str(e)}'
            )
    
    async def check_stream_content(self, url: str, sample_size: int = 1024) -> Dict[str, Any]:
        """Check stream content by downloading a small sample"""
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    # Read small sample
                    content = await response.content.read(sample_size)
                    
                    # Analyze content
                    analysis = {
                        'has_content': len(content) > 0,
                        'content_size': len(content),
                        'content_type': response.headers.get('content-type', ''),
                        'is_video_stream': False,
                        'is_playlist': False
                    }
                    
                    # Check if it's a video stream
                    content_type = analysis['content_type'].lower()
                    if any(vtype in content_type for vtype in ['video', 'stream', 'mpegts', 'mp4']):
                        analysis['is_video_stream'] = True
                    
                    # Check if it's a playlist (M3U8, etc.)
                    if content.startswith(b'#EXTM3U') or b'.m3u8' in content:
                        analysis['is_playlist'] = True
                    
                    return analysis
                    
        except Exception as e:
            return {
                'has_content': False,
                'error': str(e)
            }
        
        return {'has_content': False}
    
    async def check_channel_health(self, channel: Dict[str, Any]) -> ChannelHealthReport:
        """Check health of all streams for a channel"""
        streams = channel.get('streams', [])
        if not streams:
            return ChannelHealthReport(
                channel_name=channel.get('name', 'Unknown'),
                channel_id=channel.get('id', ''),
                streams=[]
            )
        
        # Check all stream URLs
        tasks = []
        for stream in streams:
            url = stream.get('url', '')
            if url:
                tasks.append(self.check_stream_health(url))
        
        stream_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out exceptions and create health objects
        health_results = []
        for result in stream_results:
            if isinstance(result, StreamHealth):
                health_results.append(result)
            elif isinstance(result, Exception):
                logger.error(f"Stream check failed: {result}")
        
        return ChannelHealthReport(
            channel_name=channel.get('name', 'Unknown'),
            channel_id=channel.get('id', ''),
            streams=health_results
        )
    
    async def check_batch_health(self, channels: List[Dict[str, Any]], 
                               progress_callback=None) -> List[ChannelHealthReport]:
        """Check health of multiple channels with progress tracking"""
        reports = []
        
        # Process in smaller batches to manage memory and connections
        batch_size = min(self.max_concurrent, 20)
        total_channels = len(channels)
        
        for i in range(0, total_channels, batch_size):
            batch = channels[i:i + batch_size]
            batch_tasks = []
            
            for channel in batch:
                task = self.check_channel_health(channel)
                batch_tasks.append(task)
            
            # Process batch
            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
            
            # Add successful results
            for result in batch_results:
                if isinstance(result, ChannelHealthReport):
                    reports.append(result)
                    
                    # Store in history
                    self.health_history[result.channel_id] = result
                elif isinstance(result, Exception):
                    logger.error(f"Channel health check failed: {result}")
            
            # Progress callback
            if progress_callback:
                progress = min(i + batch_size, total_channels)
                progress_callback(progress, total_channels)
            
            # Small delay between batches
            if i + batch_size < total_channels:
                await asyncio.sleep(0.5)
        
        return reports
    
    def generate_health_report(self, reports: List[ChannelHealthReport]) -> Dict[str, Any]:
        """Generate comprehensive health report"""
        if not reports:
            return {'error': 'No health data available'}
        
        total_channels = len(reports)
        total_streams = sum(len(r.streams) for r in reports)
        
        # Calculate statistics
        online_channels = sum(1 for r in reports if r.success_rate > 0)
        offline_channels = total_channels - online_channels
        
        all_streams = []
        for report in reports:
            all_streams.extend(report.streams)
        
        online_streams = [s for s in all_streams if s.status == 'online']
        offline_streams = [s for s in all_streams if s.status == 'offline']
        timeout_streams = [s for s in all_streams if s.status == 'timeout']
        error_streams = [s for s in all_streams if s.status == 'error']
        
        # Response time statistics
        response_times = [s.response_time for s in online_streams]
        avg_response_time = statistics.mean(response_times) if response_times else 0
        median_response_time = statistics.median(response_times) if response_times else 0
        
        # Find problematic channels
        problematic_channels = [r for r in reports if r.success_rate < 50]
        best_channels = [r for r in reports if r.success_rate == 100 and r.average_response_time < 2.0]
        
        report = {
            'summary': {
                'total_channels': total_channels,
                'total_streams': total_streams,
                'online_channels': online_channels,
                'offline_channels': offline_channels,
                'overall_success_rate': (online_channels / total_channels * 100) if total_channels > 0 else 0
            },
            'stream_statistics': {
                'online_streams': len(online_streams),
                'offline_streams': len(offline_streams),
                'timeout_streams': len(timeout_streams),
                'error_streams': len(error_streams),
                'stream_success_rate': (len(online_streams) / total_streams * 100) if total_streams > 0 else 0
            },
            'performance': {
                'average_response_time': avg_response_time,
                'median_response_time': median_response_time,
                'fastest_stream': min(online_streams, key=lambda x: x.response_time).url if online_streams else None,
                'slowest_stream': max(online_streams, key=lambda x: x.response_time).url if online_streams else None
            },
            'issues': {
                'problematic_channels': len(problematic_channels),
                'problematic_channel_names': [r.channel_name for r in problematic_channels[:10]],  # Top 10
                'common_errors': self._analyze_common_errors(all_streams)
            },
            'recommendations': {
                'best_performing_channels': [r.channel_name for r in best_channels[:10]],
                'channels_needing_attention': [r.channel_name for r in problematic_channels[:5]]
            },
            'timestamp': time.time()
        }
        
        return report
    
    def _analyze_common_errors(self, streams: List[StreamHealth]) -> Dict[str, int]:
        """Analyze common error patterns"""
        error_counts = {}
        
        for stream in streams:
            if stream.status in ['offline', 'timeout', 'error']:
                error_key = stream.error_message or f'{stream.status}_{stream.status_code}'
                error_counts[error_key] = error_counts.get(error_key, 0) + 1
        
        # Return top 10 most common errors
        sorted_errors = sorted(error_counts.items(), key=lambda x: x[1], reverse=True)
        return dict(sorted_errors[:10])
    
    def get_channel_history(self, channel_id: str) -> Optional[ChannelHealthReport]:
        """Get health history for a specific channel"""
        return self.health_history.get(channel_id)
    
    def export_report(self, reports: List[ChannelHealthReport], filepath: str):
        """Export health report to JSON file"""
        try:
            report_data = {
                'health_report': self.generate_health_report(reports),
                'channel_details': [asdict(report) for report in reports],
                'export_timestamp': time.time()
            }
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(report_data, f, indent=2, ensure_ascii=False, default=str)
            
            logger.info(f"Health report exported to: {filepath}")
        except Exception as e:
            logger.error(f"Failed to export health report: {e}")

# Integration with IPTV Manager
class IPTVHealthMonitor:
    """Integration class for IPTV Manager health monitoring"""
    
    def __init__(self, iptv_manager):
        self.iptv_manager = iptv_manager
        self.health_checker = StreamHealthChecker()
    
    async def monitor_provider_health(self, provider_name: str) -> Dict[str, Any]:
        """Monitor health of a specific provider"""
        config = self.iptv_manager.load_config()
        providers = config.get('providers', [])
        
        for provider in providers:
            if provider.get('name') == provider_name and provider.get('enabled', True):
                # Get M3U content
                m3u_content = self.iptv_manager.download_m3u(provider_name)
                if not m3u_content:
                    return {'error': f'Failed to download M3U for {provider_name}'}
                
                # Parse channels
                parsed_content = self.iptv_manager.parse_m3u_content(
                    m3u_content, provider, {}, {}
                )
                
                # Convert to channel list
                all_channels = []
                for category, channels in parsed_content.items():
                    for channel_name, channel_data in channels.items():
                        channel_data['id'] = f"{provider_name}_{channel_name}"
                        all_channels.append(channel_data)
                
                # Check health
                async with self.health_checker:
                    reports = await self.health_checker.check_batch_health(all_channels)
                    health_report = self.health_checker.generate_health_report(reports)
                
                return {
                    'provider': provider_name,
                    'health_report': health_report,
                    'detailed_reports': reports
                }
        
        return {'error': f'Provider {provider_name} not found or disabled'}
    
    async def monitor_all_providers(self) -> Dict[str, Any]:
        """Monitor health of all enabled providers"""
        config = self.iptv_manager.load_config()
        providers = config.get('providers', [])
        
        all_reports = {}
        
        for provider in providers:
            if provider.get('enabled', True):
                provider_name = provider.get('name', '')
                try:
                    report = await self.monitor_provider_health(provider_name)
                    all_reports[provider_name] = report
                except Exception as e:
                    logger.error(f"Failed to monitor provider {provider_name}: {e}")
                    all_reports[provider_name] = {'error': str(e)}
        
        return all_reports

# Example usage
async def main():
    """Example usage of stream health checker"""
    
    # Sample channels for testing
    test_channels = [
        {
            'name': 'Test Channel 1',
            'id': 'test1',
            'streams': [
                {'url': 'http://example.com/stream1.m3u8'},
                {'url': 'http://example.com/stream2.ts'}
            ]
        },
        {
            'name': 'Test Channel 2', 
            'id': 'test2',
            'streams': [
                {'url': 'http://invalid-url.com/stream.m3u8'}
            ]
        }
    ]
    
    # Check health
    async with StreamHealthChecker(max_concurrent=5, timeout=10) as checker:
        def progress_callback(current, total):
            print(f"Progress: {current}/{total} channels checked")
        
        reports = await checker.check_batch_health(test_channels, progress_callback)
        health_report = checker.generate_health_report(reports)
        
        print(json.dumps(health_report, indent=2, default=str))

if __name__ == "__main__":
    asyncio.run(main())
