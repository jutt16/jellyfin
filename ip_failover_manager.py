#!/usr/bin/env python3
"""
IP-Based Failover Manager for IPTV Compliance
Automatically switches users to different failover channels/providers based on IP addresses
to maintain compliance with IPTV providers that only allow 1 IP connection per list
"""

import asyncio
import logging
import json
import time
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, asdict
from collections import defaultdict
import ipaddress
import aiohttp
from aiohttp import web
import sqlite3
import threading

logger = logging.getLogger(__name__)

@dataclass
class IPSession:
    """Represents an active IP session"""
    ip_address: str
    user_id: str
    provider_name: str
    failover_tier: int
    session_start: datetime
    last_activity: datetime
    channels_accessed: List[str]
    connection_count: int

@dataclass
class FailoverProvider:
    """Represents a failover IPTV provider"""
    name: str
    tier: int  # 0 = primary, 1 = secondary, 2 = tertiary, etc.
    m3u_url: str
    xtream_config: Optional[Dict] = None
    max_concurrent_ips: int = 1
    active_ips: Set[str] = None
    health_status: str = "unknown"  # healthy, degraded, offline
    last_health_check: Optional[datetime] = None

    def __post_init__(self):
        if self.active_ips is None:
            self.active_ips = set()

class IPFailoverDatabase:
    """SQLite database for IP failover tracking"""
    
    def __init__(self, db_path: str = "ip_failover.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize database tables"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ip_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ip_address TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    provider_name TEXT NOT NULL,
                    failover_tier INTEGER NOT NULL,
                    session_start TIMESTAMP NOT NULL,
                    last_activity TIMESTAMP NOT NULL,
                    channels_accessed TEXT,  -- JSON array
                    connection_count INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS provider_health (
                    provider_name TEXT PRIMARY KEY,
                    tier INTEGER NOT NULL,
                    health_status TEXT NOT NULL,
                    last_check TIMESTAMP NOT NULL,
                    response_time_ms INTEGER,
                    error_count INTEGER DEFAULT 0,
                    success_rate REAL DEFAULT 100.0
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS failover_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ip_address TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    from_provider TEXT NOT NULL,
                    to_provider TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create indexes for performance
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ip_sessions_ip ON ip_sessions(ip_address)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ip_sessions_provider ON ip_sessions(provider_name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_failover_events_ip ON failover_events(ip_address)")
    
    def add_session(self, session: IPSession):
        """Add or update IP session"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO ip_sessions 
                (ip_address, user_id, provider_name, failover_tier, session_start, 
                 last_activity, channels_accessed, connection_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session.ip_address, session.user_id, session.provider_name,
                session.failover_tier, session.session_start, session.last_activity,
                json.dumps(session.channels_accessed), session.connection_count
            ))
    
    def get_active_sessions(self, cutoff_minutes: int = 30) -> List[IPSession]:
        """Get active sessions within cutoff time"""
        cutoff_time = datetime.now() - timedelta(minutes=cutoff_minutes)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT ip_address, user_id, provider_name, failover_tier,
                       session_start, last_activity, channels_accessed, connection_count
                FROM ip_sessions 
                WHERE last_activity > ?
            """, (cutoff_time,))
            
            sessions = []
            for row in cursor.fetchall():
                sessions.append(IPSession(
                    ip_address=row[0],
                    user_id=row[1],
                    provider_name=row[2],
                    failover_tier=row[3],
                    session_start=datetime.fromisoformat(row[4]),
                    last_activity=datetime.fromisoformat(row[5]),
                    channels_accessed=json.loads(row[6] or "[]"),
                    connection_count=row[7]
                ))
            
            return sessions
    
    def log_failover_event(self, ip_address: str, user_id: str, from_provider: str, 
                          to_provider: str, reason: str):
        """Log a failover event"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO failover_events 
                (ip_address, user_id, from_provider, to_provider, reason)
                VALUES (?, ?, ?, ?, ?)
            """, (ip_address, user_id, from_provider, to_provider, reason))

class IPFailoverManager:
    """Main IP-based failover manager"""
    
    def __init__(self, config_path: str = "ip_failover_config.json"):
        self.config_path = config_path
        self.db = IPFailoverDatabase()
        self.providers: Dict[str, FailoverProvider] = {}
        self.active_sessions: Dict[str, IPSession] = {}  # ip_address -> session
        self.ip_to_provider_mapping: Dict[str, str] = {}  # ip -> provider_name
        self.monitoring_active = False
        self.load_config()
    
    def load_config(self):
        """Load failover configuration"""
        try:
            with open(self.config_path, 'r') as f:
                config = json.load(f)
            
            # Load providers
            for provider_config in config.get('providers', []):
                provider = FailoverProvider(
                    name=provider_config['name'],
                    tier=provider_config['tier'],
                    m3u_url=provider_config['m3u_url'],
                    xtream_config=provider_config.get('xtream_config'),
                    max_concurrent_ips=provider_config.get('max_concurrent_ips', 1)
                )
                self.providers[provider.name] = provider
            
            logger.info(f"Loaded {len(self.providers)} failover providers")
            
        except FileNotFoundError:
            logger.warning(f"Config file {self.config_path} not found, creating default")
            self.create_default_config()
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            self.create_default_config()
    
    def create_default_config(self):
        """Create default failover configuration"""
        default_config = {
            "providers": [
                {
                    "name": "Primary_Provider",
                    "tier": 0,
                    "m3u_url": "http://primary-provider.com/playlist.m3u8",
                    "max_concurrent_ips": 1,
                    "xtream_config": {
                        "server_url": "http://primary-provider.com:8080",
                        "username": "user1",
                        "password": "pass1"
                    }
                },
                {
                    "name": "Secondary_Provider",
                    "tier": 1,
                    "m3u_url": "http://secondary-provider.com/playlist.m3u8",
                    "max_concurrent_ips": 1,
                    "xtream_config": {
                        "server_url": "http://secondary-provider.com:8080",
                        "username": "user2",
                        "password": "pass2"
                    }
                },
                {
                    "name": "Tertiary_Provider",
                    "tier": 2,
                    "m3u_url": "http://tertiary-provider.com/playlist.m3u8",
                    "max_concurrent_ips": 1
                }
            ],
            "settings": {
                "session_timeout_minutes": 30,
                "health_check_interval_seconds": 300,
                "failover_retry_attempts": 3,
                "ip_detection_methods": ["x-forwarded-for", "x-real-ip", "remote-addr"]
            }
        }
        
        with open(self.config_path, 'w') as f:
            json.dump(default_config, f, indent=2)
        
        logger.info(f"Created default config at {self.config_path}")
        self.load_config()
    
    def get_client_ip(self, request) -> str:
        """Extract client IP from request with various methods"""
        # Try different headers in order of preference
        ip_headers = [
            'X-Forwarded-For',
            'X-Real-IP',
            'X-Client-IP',
            'CF-Connecting-IP'  # Cloudflare
        ]
        
        for header in ip_headers:
            ip = request.headers.get(header)
            if ip:
                # Handle comma-separated IPs (take first one)
                ip = ip.split(',')[0].strip()
                try:
                    # Validate IP address
                    ipaddress.ip_address(ip)
                    return ip
                except ValueError:
                    continue
        
        # Fallback to remote address
        return request.remote
    
    def determine_failover_provider(self, ip_address: str, user_id: str) -> str:
        """Determine which provider to assign to this IP/user"""
        # Check if IP already has an active session
        if ip_address in self.active_sessions:
            session = self.active_sessions[ip_address]
            provider = self.providers[session.provider_name]
            
            # Check if current provider is still healthy and has capacity
            if (provider.health_status == "healthy" and 
                len(provider.active_ips) <= provider.max_concurrent_ips):
                return session.provider_name
        
        # Find best available provider
        sorted_providers = sorted(self.providers.values(), key=lambda p: p.tier)
        
        for provider in sorted_providers:
            if (provider.health_status in ["healthy", "unknown"] and
                len(provider.active_ips) < provider.max_concurrent_ips):
                return provider.name
        
        # If all providers are at capacity, use round-robin on lowest tier
        lowest_tier_providers = [p for p in sorted_providers if p.tier == sorted_providers[0].tier]
        
        # Simple hash-based assignment for consistency
        ip_hash = int(hashlib.md5(ip_address.encode()).hexdigest(), 16)
        selected_provider = lowest_tier_providers[ip_hash % len(lowest_tier_providers)]
        
        return selected_provider.name
    
    async def handle_stream_request(self, request) -> web.Response:
        """Handle incoming stream request with IP-based failover"""
        client_ip = self.get_client_ip(request)
        user_id = request.headers.get('X-User-ID', f'user_{client_ip}')
        channel_id = request.match_info.get('channel_id', 'unknown')
        
        logger.info(f"Stream request from IP {client_ip}, User {user_id}, Channel {channel_id}")
        
        # Determine provider for this IP
        provider_name = self.determine_failover_provider(client_ip, user_id)
        provider = self.providers[provider_name]
        
        # Check if we need to failover
        current_session = self.active_sessions.get(client_ip)
        if current_session and current_session.provider_name != provider_name:
            # Log failover event
            self.db.log_failover_event(
                client_ip, user_id, current_session.provider_name, 
                provider_name, "IP capacity or health-based failover"
            )
            logger.info(f"Failover: {client_ip} from {current_session.provider_name} to {provider_name}")
        
        # Update session tracking
        now = datetime.now()
        session = IPSession(
            ip_address=client_ip,
            user_id=user_id,
            provider_name=provider_name,
            failover_tier=provider.tier,
            session_start=current_session.session_start if current_session else now,
            last_activity=now,
            channels_accessed=list(set((current_session.channels_accessed if current_session else []) + [channel_id])),
            connection_count=(current_session.connection_count if current_session else 0) + 1
        )
        
        self.active_sessions[client_ip] = session
        provider.active_ips.add(client_ip)
        self.db.add_session(session)
        
        # Generate appropriate stream URL
        if provider.xtream_config:
            # Xtream API format
            stream_url = f"{provider.xtream_config['server_url']}/live/{provider.xtream_config['username']}/{provider.xtream_config['password']}/{channel_id}.m3u8"
        else:
            # Direct M3U format - proxy the original stream
            stream_url = await self.get_channel_stream_from_m3u(provider.m3u_url, channel_id)
        
        if not stream_url:
            return web.Response(status=404, text="Channel not found")
        
        # Proxy the stream
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(stream_url) as resp:
                    if resp.status == 200:
                        content = await resp.read()
                        return web.Response(
                            body=content,
                            content_type=resp.content_type,
                            headers={
                                'X-Failover-Provider': provider_name,
                                'X-Failover-Tier': str(provider.tier),
                                'X-Client-IP': client_ip
                            }
                        )
                    else:
                        # Try next tier provider on failure
                        return await self.try_failover_stream(client_ip, user_id, channel_id, provider.tier + 1)
        
        except Exception as e:
            logger.error(f"Stream proxy error: {e}")
            return await self.try_failover_stream(client_ip, user_id, channel_id, provider.tier + 1)
    
    async def try_failover_stream(self, client_ip: str, user_id: str, channel_id: str, min_tier: int) -> web.Response:
        """Try failover to next available provider"""
        available_providers = [p for p in self.providers.values() 
                             if p.tier >= min_tier and p.health_status != "offline"]
        
        if not available_providers:
            return web.Response(status=503, text="No available providers")
        
        # Sort by tier and try each one
        available_providers.sort(key=lambda p: p.tier)
        
        for provider in available_providers:
            try:
                if provider.xtream_config:
                    stream_url = f"{provider.xtream_config['server_url']}/live/{provider.xtream_config['username']}/{provider.xtream_config['password']}/{channel_id}.m3u8"
                else:
                    stream_url = await self.get_channel_stream_from_m3u(provider.m3u_url, channel_id)
                
                if stream_url:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(stream_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                            if resp.status == 200:
                                # Update session to use this provider
                                self.active_sessions[client_ip].provider_name = provider.name
                                self.active_sessions[client_ip].failover_tier = provider.tier
                                provider.active_ips.add(client_ip)
                                
                                # Log successful failover
                                self.db.log_failover_event(
                                    client_ip, user_id, "failed_provider", 
                                    provider.name, f"Automatic failover to tier {provider.tier}"
                                )
                                
                                content = await resp.read()
                                return web.Response(
                                    body=content,
                                    content_type=resp.content_type,
                                    headers={
                                        'X-Failover-Provider': provider.name,
                                        'X-Failover-Tier': str(provider.tier),
                                        'X-Client-IP': client_ip,
                                        'X-Failover-Used': 'true'
                                    }
                                )
            
            except Exception as e:
                logger.warning(f"Failover attempt failed for provider {provider.name}: {e}")
                continue
        
        return web.Response(status=503, text="All failover providers failed")
    
    async def get_channel_stream_from_m3u(self, m3u_url: str, channel_id: str) -> Optional[str]:
        """Extract specific channel stream URL from M3U playlist"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(m3u_url) as resp:
                    if resp.status == 200:
                        content = await resp.text()
                        lines = content.split('\n')
                        
                        for i, line in enumerate(lines):
                            if line.startswith('#EXTINF:') and channel_id in line:
                                # Next line should be the stream URL
                                if i + 1 < len(lines):
                                    return lines[i + 1].strip()
                        
                        # If channel_id not found, try to match by line number or other criteria
                        # This is a fallback - you might need to adjust based on your M3U format
                        stream_lines = [line.strip() for line in lines if line.strip() and not line.startswith('#')]
                        if stream_lines:
                            # Use hash of channel_id to select a stream
                            channel_hash = int(hashlib.md5(channel_id.encode()).hexdigest(), 16)
                            selected_stream = stream_lines[channel_hash % len(stream_lines)]
                            return selected_stream
        
        except Exception as e:
            logger.error(f"Failed to fetch M3U playlist {m3u_url}: {e}")
        
        return None
    
    async def health_check_providers(self):
        """Perform health checks on all providers"""
        for provider in self.providers.values():
            try:
                start_time = time.time()
                
                if provider.xtream_config:
                    # Check Xtream API health
                    health_url = f"{provider.xtream_config['server_url']}/player_api.php?username={provider.xtream_config['username']}&password={provider.xtream_config['password']}&action=get_live_categories"
                else:
                    # Check M3U availability
                    health_url = provider.m3u_url
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(health_url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                        response_time = int((time.time() - start_time) * 1000)
                        
                        if resp.status == 200:
                            provider.health_status = "healthy"
                        elif resp.status in [502, 503, 504]:
                            provider.health_status = "degraded"
                        else:
                            provider.health_status = "offline"
                        
                        provider.last_health_check = datetime.now()
                        
                        logger.info(f"Provider {provider.name}: {provider.health_status} ({response_time}ms)")
            
            except Exception as e:
                provider.health_status = "offline"
                provider.last_health_check = datetime.now()
                logger.error(f"Health check failed for {provider.name}: {e}")
    
    async def cleanup_expired_sessions(self):
        """Clean up expired IP sessions"""
        cutoff_time = datetime.now() - timedelta(minutes=30)
        expired_ips = []
        
        for ip, session in self.active_sessions.items():
            if session.last_activity < cutoff_time:
                expired_ips.append(ip)
                
                # Remove IP from provider's active set
                if session.provider_name in self.providers:
                    self.providers[session.provider_name].active_ips.discard(ip)
        
        for ip in expired_ips:
            del self.active_sessions[ip]
        
        if expired_ips:
            logger.info(f"Cleaned up {len(expired_ips)} expired sessions")
    
    async def start_monitoring(self):
        """Start background monitoring tasks"""
        self.monitoring_active = True
        logger.info("Starting IP failover monitoring")
        
        while self.monitoring_active:
            try:
                # Health check providers every 5 minutes
                await self.health_check_providers()
                
                # Clean up expired sessions
                await self.cleanup_expired_sessions()
                
                # Wait before next cycle
                await asyncio.sleep(300)  # 5 minutes
                
            except Exception as e:
                logger.error(f"Monitoring error: {e}")
                await asyncio.sleep(60)  # Wait 1 minute on error
    
    def stop_monitoring(self):
        """Stop background monitoring"""
        self.monitoring_active = False
        logger.info("Stopped IP failover monitoring")
    
    def get_status_report(self) -> Dict:
        """Get comprehensive status report"""
        active_sessions = self.db.get_active_sessions()
        
        provider_stats = {}
        for name, provider in self.providers.items():
            provider_stats[name] = {
                'tier': provider.tier,
                'health_status': provider.health_status,
                'active_ips': len(provider.active_ips),
                'max_concurrent_ips': provider.max_concurrent_ips,
                'last_health_check': provider.last_health_check.isoformat() if provider.last_health_check else None
            }
        
        return {
            'total_active_sessions': len(active_sessions),
            'total_providers': len(self.providers),
            'healthy_providers': len([p for p in self.providers.values() if p.health_status == "healthy"]),
            'provider_stats': provider_stats,
            'active_sessions_by_provider': {
                name: len([s for s in active_sessions if s.provider_name == name])
                for name in self.providers.keys()
            }
        }

# Web API for IP Failover Manager
async def create_failover_app(manager: IPFailoverManager) -> web.Application:
    """Create web application for IP failover management"""
    
    async def handle_stream(request):
        return await manager.handle_stream_request(request)
    
    async def handle_status(request):
        status = manager.get_status_report()
        return web.json_response(status)
    
    async def handle_sessions(request):
        sessions = manager.db.get_active_sessions()
        sessions_data = [asdict(session) for session in sessions]
        # Convert datetime objects to strings
        for session_data in sessions_data:
            session_data['session_start'] = session_data['session_start'].isoformat()
            session_data['last_activity'] = session_data['last_activity'].isoformat()
        return web.json_response(sessions_data)
    
    app = web.Application()
    app.router.add_get('/stream/{channel_id}', handle_stream)
    app.router.add_get('/status', handle_status)
    app.router.add_get('/sessions', handle_sessions)
    
    return app

async def main():
    """Main function for standalone operation"""
    logging.basicConfig(level=logging.INFO)
    
    manager = IPFailoverManager()
    
    # Start monitoring in background
    monitoring_task = asyncio.create_task(manager.start_monitoring())
    
    # Create and start web server
    app = await create_failover_app(manager)
    runner = web.AppRunner(app)
    await runner.setup()
    
    site = web.TCPSite(runner, '0.0.0.0', 8766)
    await site.start()
    
    logger.info("IP Failover Manager started on http://0.0.0.0:8766")
    logger.info("Endpoints:")
    logger.info("  GET /stream/{channel_id} - Stream with IP-based failover")
    logger.info("  GET /status - System status")
    logger.info("  GET /sessions - Active sessions")
    
    try:
        await monitoring_task
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        manager.stop_monitoring()
        await runner.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
