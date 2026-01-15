#!/usr/bin/env python3
"""
Enhanced Jellyfin Management Script with Complete IPTV Failover Support
Manages SynoCommunity Jellyfin with advanced IPTV proxy failover capabilities
"""

import subprocess
import sys
import logging
import time
import requests
import json
import asyncio
import aiohttp
import os
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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
        
        try:
            await asyncio.gather(
                self.monitor_services(),
                self.handle_failover_events(),
                self.cleanup_stale_data(),
                return_exceptions=True
            )
        except Exception as e:
            logger.error(f"Failover monitoring error: {e}")
            self.running = False
    
    async def monitor_services(self):
        """Monitor all services for health and trigger failover if needed."""
        while self.running:
            try:
                tasks = []
                for service_name, config in self.services.items():
                    tasks.append(self.check_service_health(service_name, config))
                
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                for i, result in enumerate(results):
                    service_name = list(self.services.keys())[i]
                    if isinstance(result, Exception) or not result:
                        await self.handle_service_failure(service_name)
                    else:
                        # Reset failure count on success
                        self.failure_counts[service_name] = 0
                        
                await asyncio.sleep(self.check_interval)
                
            except Exception as e:
                logger.error(f"Error in service monitoring: {e}")
                await asyncio.sleep(self.check_interval)
    
    async def check_service_health(self, service_name, config):
        """Check health of a specific service."""
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(config['url']) as response:
                    return response.status < 400
        except Exception as e:
            logger.debug(f"Health check failed for {service_name}: {e}")
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
                await self.restart_docker_service('threadfin-primary')
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
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Error in failover event handler: {e}")
                await asyncio.sleep(5)
    
    async def cleanup_stale_data(self):
        """Clean up stale data and sessions."""
        while self.running:
            try:
                # Cleanup logic here
                await asyncio.sleep(300)  # Every 5 minutes
                
            except Exception as e:
                logger.error(f"Error in cleanup: {e}")
                await asyncio.sleep(300)
    
    def stop_monitoring(self):
        """Stop the failover monitoring system."""
        self.running = False
        logger.info("Failover monitoring stopped")


class MosaicManager:
    """Manages FFmpeg Mosaic Plugin sessions."""

    def __init__(self, jellyfin_url: str, api_key: str):
        self.base_url = f"{jellyfin_url.rstrip('/')}/FfmpegMosaic"
        self.headers = {
            "X-Emby-Token": api_key,
            "Content-Type": "application/json"
        }
        self.active_sessions = {}  # In-memory cache

    def start_session(self, channel_ids: List[str]) -> Optional[Dict]:
        """Start a new mosaic session."""
        endpoint = f"{self.base_url}/Start"
        payload = {"ChannelIds": channel_ids}
        try:
            response = requests.post(endpoint, headers=self.headers, json=payload, timeout=20)
            response.raise_for_status()
            data = response.json()
            self.active_sessions[data['sessionId']] = data['url']
            logger.info(f"Started mosaic session {data['sessionId']}")
            return data
        except requests.RequestException as e:
            logger.error(f"Failed to start mosaic session: {e}")
            return None

    def stop_session(self, session_id: str) -> bool:
        """Stop an active mosaic session."""
        endpoint = f"{self.base_url}/Stop/{session_id}"
        try:
            response = requests.post(endpoint, headers=self.headers, timeout=10)
            response.raise_for_status()
            if session_id in self.active_sessions:
                del self.active_sessions[session_id]
            logger.info(f"Stopped mosaic session {session_id}")
            return True
        except requests.RequestException as e:
            logger.error(f"Failed to stop mosaic session {session_id}: {e}")
            return False

    def list_sessions(self) -> Dict:
        """List active mosaic sessions (from cache)."""
        return self.active_sessions


class JellyfinEnhancedManager:
    def __init__(self):
        self.base_dir = Path("/volume2/jellyfin-enhanced")
        self.docker_services = [
            'threadfin-primary', 
            'iptv-proxy-failover', 
            'iptv-failover-manager', 
            'iptv-loadbalancer',
            'jellyfin-cache', 
            'jellyfin-nginx'
        ]
        
        self.service_ports = {
            'threadfin-primary': 34400,
            'iptv-proxy-failover': 8080,
            'iptv-loadbalancer': 34500,
            'jellyfin-cache': 6379,
            'jellyfin-nginx': [80, 443],
            'jellyfin': 8096
        }
        
        # Service dependencies mapping
        self.service_dependencies = {
            'jellyfin-cache': [],  # No dependencies
            'iptv-proxy-failover': ['jellyfin-cache'],
            'threadfin-primary': ['jellyfin-cache'],
            'iptv-loadbalancer': ['threadfin-primary', 'iptv-proxy-failover'],
            'iptv-failover-manager': ['iptv-loadbalancer'],
            'jellyfin-nginx': ['iptv-loadbalancer'],
            'jellyfin': ['jellyfin-nginx', 'iptv-loadbalancer']
        }
        
        # Failover endpoints
        self.failover_endpoints = {
            'load_balancer': 'http://127.0.0.1:34500',
            'threadfin': 'http://127.0.0.1:34400',
            'iptv_proxy': 'http://127.0.0.1:8080',
            'failover_manager': 'http://127.0.0.1:8081'  # If exposed
        }
        
        # Initialize async failover manager
        self.async_failover = AsyncFailoverManager()
        self.monitoring_task = None

        # Load configuration from environment or config file
        jellyfin_url = os.getenv('JELLYFIN_URL', 'http://localhost:8096')
        api_key = os.getenv('JELLYFIN_API_KEY', '')
        
        if not api_key:
            # Try to load from config file
            config_file = self.base_dir / 'jellyfin_config.json'
            if config_file.exists():
                try:
                    with open(config_file, 'r') as f:
                        config = json.load(f)
                        api_key = config.get('api_key', '')
                        jellyfin_url = config.get('url', jellyfin_url)
                except Exception as e:
                    logger.warning(f"Failed to load config file: {e}")
        
        self.mosaic_manager = MosaicManager(jellyfin_url, api_key) if api_key else None
    
    def _run_command(self, command: List[str], capture_output: bool = True) -> subprocess.CompletedProcess:
        """Run shell command with error handling"""
        try:
            result = subprocess.run(command, capture_output=capture_output, text=True, timeout=30)
            return result
        except subprocess.TimeoutExpired:
            logger.error(f"Command timed out: {' '.join(command)}")
            raise
        except Exception as e:
            logger.error(f"Command failed: {' '.join(command)} - {e}")
            raise
    
    def verify_service_dependencies(self, service_name: str) -> Dict[str, bool]:
        """Check service dependency chain health"""
        dependencies = self.service_dependencies.get(service_name, [])
        dependency_status = {}
        
        for dep in dependencies:
            if dep == 'jellyfin':
                dependency_status[dep] = self.verify_jellyfin_health()
            elif dep in self.docker_services:
                dependency_status[dep] = self.verify_service_health(dep)
            else:
                dependency_status[dep] = False
        
        return dependency_status
    
    def optimize_cache_performance(self):
        """Redis cache optimization and cleanup"""
        print("🔧 Optimizing Redis Cache Performance...")
        
        try:
            # Check Redis connection
            result = self._run_command(['redis-cli', 'ping'])
            if result.returncode != 0:
                print("❌ Redis not accessible")
                return False
            
            # Get cache statistics
            stats_result = self._run_command(['redis-cli', 'info', 'memory'])
            if stats_result.returncode == 0:
                print("📊 Current Redis Memory Usage:")
                for line in stats_result.stdout.split('\n'):
                    if 'used_memory_human' in line or 'used_memory_peak_human' in line:
                        print(f"   {line}")
            
            # Cleanup expired keys
            cleanup_result = self._run_command(['redis-cli', 'eval', 
                'return redis.call("del", unpack(redis.call("keys", ARGV[1])))', 
                '0', '*:expired:*'])
            
            # Optimize memory usage
            self._run_command(['redis-cli', 'config', 'set', 'maxmemory-policy', 'allkeys-lru'])
            
            # Get final statistics
            final_stats = self._run_command(['redis-cli', 'info', 'stats'])
            if final_stats.returncode == 0:
                print("📈 Cache Optimization Complete:")
                for line in final_stats.stdout.split('\n'):
                    if 'keyspace_hits' in line or 'keyspace_misses' in line:
                        print(f"   {line}")
            
            print("✅ Cache optimization completed")
            return True
            
        except Exception as e:
            print(f"❌ Cache optimization failed: {e}")
            logger.error(f"Cache optimization error: {e}")
            return False
    
    async def start_continuous_monitoring(self):
        """Start background async monitoring like AsyncFailoverManager"""
        print("🔄 Starting Continuous Background Monitoring...")
        
        try:
            # Update service URLs for our specific setup
            self.async_failover.services.update({
                'threadfin': {'url': 'http://localhost:34400', 'critical': True},
                'loadbalancer': {'url': 'http://localhost:34500/health', 'critical': True},
                'iptv_proxy': {'url': 'http://localhost:8080/health', 'critical': False},
                'nginx': {'url': 'http://localhost:80', 'critical': False},
                'redis': {'url': 'http://localhost:6379', 'critical': False}
            })
            
            print("📡 Monitoring Services:")
            for service_name, config in self.async_failover.services.items():
                critical_status = "Critical" if config['critical'] else "Non-Critical"
                print(f"   • {service_name.title()}: {config['url']} ({critical_status})")
            
            print(f"⏱️  Check Interval: {self.async_failover.check_interval} seconds")
            print(f"🚨 Failure Threshold: {self.async_failover.max_failures} failures")
            print(f"🔄 Auto-Restart: Enabled")
            
            # Start monitoring in background
            self.monitoring_task = asyncio.create_task(
                self.async_failover.start_failover_monitoring()
            )
            
            print("✅ Background monitoring started successfully")
            print("💡 Use 'python3 manage_enhanced.py stop-monitoring' to stop")
            
            return True
            
        except Exception as e:
            print(f"❌ Failed to start continuous monitoring: {e}")
            logger.error(f"Continuous monitoring startup error: {e}")
            return False
    
    def stop_continuous_monitoring(self):
        """Stop background async monitoring"""
        print("⏹️  Stopping Continuous Background Monitoring...")
        
        try:
            if self.monitoring_task and not self.monitoring_task.done():
                self.async_failover.stop_monitoring()
                self.monitoring_task.cancel()
                print("✅ Background monitoring stopped")
            else:
                print("ℹ️  No active monitoring to stop")
            
        except Exception as e:
            print(f"❌ Error stopping monitoring: {e}")
            logger.error(f"Stop monitoring error: {e}")
    
    def integrate_with_async_failover(self):
        """Integration point with AsyncFailoverManager"""
        print("🔗 Integrating with Async Failover Manager...")
        
        # Verify async failover manager is available
        if not hasattr(self, 'async_failover'):
            print("❌ Async failover manager not initialized")
            return False
        
        # Update service configurations to match our deployment
        service_mapping = {
            'jellyfin': 'http://localhost:8096/health',
            'threadfin-primary': 'http://localhost:34400',
            'iptv-loadbalancer': 'http://localhost:34500/health',
            'iptv-proxy-failover': 'http://localhost:8080/health',
            'jellyfin-nginx': 'http://localhost:80',
            'jellyfin-cache': 'http://localhost:6379'
        }
        
        # Update async failover service definitions
        updated_services = {}
        for service_name, url in service_mapping.items():
            critical = service_name in ['jellyfin', 'threadfin-primary', 'iptv-loadbalancer']
            updated_services[service_name.replace('-', '_')] = {
                'url': url,
                'critical': critical
            }
        
        self.async_failover.services = updated_services
        
        print("✅ Integration completed")
        print("📡 Updated service monitoring configuration:")
        for service_name, config in updated_services.items():
            critical_status = "Critical" if config['critical'] else "Non-Critical"
            print(f"   • {service_name.replace('_', '-').title()}: {config['url']} ({critical_status})")
        
        return True
    
    def verify_service_health(self, service_name: str) -> bool:
        """Verify if a service is healthy after restart"""
        try:
            if service_name == 'jellyfin-cache':
                result = self._run_command(['redis-cli', 'ping'], capture_output=True)
                return result.returncode == 0 and 'PONG' in result.stdout
            
            elif service_name in ['threadfin-primary', 'iptv-proxy-failover', 'iptv-loadbalancer']:
                port_map = {
                    'threadfin-primary': 34400,
                    'iptv-proxy-failover': 8080,
                    'iptv-loadbalancer': 34500
                }
                port = port_map.get(service_name)
                if port:
                    response = requests.get(f'http://127.0.0.1:{port}', timeout=5)
                    return response.status_code < 500
            
            elif service_name == 'jellyfin-nginx':
                response = requests.get('http://127.0.0.1:80', timeout=5)
                return response.status_code < 500
            
            # For other services, just check if container is running
            result = self._run_command(['docker', 'ps', '--filter', f'name={service_name}', '--format', '{{.Status}}'])
            return 'Up' in result.stdout
        
        except:
            return False
    
    def verify_jellyfin_health(self) -> bool:
        """Verify Jellyfin health"""
        try:
            response = requests.get('http://127.0.0.1:8096/health', timeout=10)
            return response.status_code == 200
        except:
            # Fallback to basic connectivity
            try:
                response = requests.get('http://127.0.0.1:8096', timeout=10)
                return response.status_code < 500
            except:
                return False
    
    def status(self):
        """Show comprehensive service status"""
        print("🔍 Jellyfin Enhanced Management - Service Status")
        print("=" * 60)
        
        # Check Jellyfin health
        jellyfin_healthy = self.verify_jellyfin_health()
        status_icon = "✅" if jellyfin_healthy else "❌"
        print(f"{status_icon} Jellyfin: {'Healthy' if jellyfin_healthy else 'Unhealthy'}")
        
        # Check Docker services
        print("\n📦 Docker Services:")
        for service in self.docker_services:
            healthy = self.verify_service_health(service)
            dependencies = self.verify_service_dependencies(service)
            
            status_icon = "✅" if healthy else "❌"
            print(f"  {status_icon} {service}: {'Running' if healthy else 'Stopped'}")
            
            # Show dependency status
            if dependencies:
                for dep, dep_healthy in dependencies.items():
                    dep_icon = "✅" if dep_healthy else "❌"
                    print(f"    └─ {dep}: {'OK' if dep_healthy else 'Failed'}")
        
        # Check service ports
        print("\n🌐 Port Status:")
        for service, ports in self.service_ports.items():
            if isinstance(ports, list):
                for port in ports:
                    try:
                        response = requests.get(f'http://127.0.0.1:{port}', timeout=5)
                        status_icon = "✅" if response.status_code < 500 else "⚠️"
                        print(f"  {status_icon} {service}:{port} - {response.status_code}")
                    except:
                        print(f"  ❌ {service}:{port} - Unreachable")
            else:
                try:
                    response = requests.get(f'http://127.0.0.1:{ports}', timeout=5)
                    status_icon = "✅" if response.status_code < 500 else "⚠️"
                    print(f"  {status_icon} {service}:{ports} - {response.status_code}")
                except:
                    print(f"  ❌ {service}:{ports} - Unreachable")
        
        # Show failover endpoints
        print("\n🔄 Failover Endpoints:")
        for name, url in self.failover_endpoints.items():
            try:
                response = requests.get(url, timeout=5)
                status_icon = "✅" if response.status_code < 500 else "⚠️"
                print(f"  {status_icon} {name}: {url} - {response.status_code}")
            except:
                print(f"  ❌ {name}: {url} - Unreachable")
        
        print("\n" + "=" * 60)


def main():
    """Main entry point with enhanced command handling"""
    if len(sys.argv) < 2:
        print("Usage: python3 manage_enhanced.py [command] [options]")
        print("\nAvailable commands:")
        print("  status              - Show comprehensive service status")
        print("  restart             - Restart all services with health checks")
        print("  monitor             - Start continuous background monitoring")
        print("  stop-monitoring     - Stop background monitoring")
        print("  optimize-cache      - Optimize Redis cache performance")
        print("  integrate           - Integrate with async failover manager")
        print("  failover [target]   - Force failover (optionally to specific target)")
        print("  reset               - Reset to primary proxy")
        print("  stats               - Show detailed failover statistics")
        print("  backup              - Create configuration backup")
        print("  logs [service]      - Show service logs")
        print("  info                - Show access information and usage guide")
        print("\n  --- Mosaic Commands ---")
        print("  mosaic-start [id1] [id2]... - Start a mosaic with channel IDs")
        print("  mosaic-stop [session_id]    - Stop a mosaic session")
        print("  mosaic-list                 - List active mosaic sessions")
        return
    
    manager = JellyfinEnhancedManager()
    command = sys.argv[1].lower()
    
    try:
        if command == "status":
            manager.status()
        
        elif command == "monitor":
            asyncio.run(manager.start_continuous_monitoring())
        
        elif command == "stop-monitoring":
            manager.stop_continuous_monitoring()
        
        elif command == "optimize-cache":
            manager.optimize_cache_performance()
        
        elif command == "integrate":
            manager.integrate_with_async_failover()
        
        elif command == "mosaic-start":
            if not manager.mosaic_manager:
                print("❌ Mosaic manager not configured. Please set JELLYFIN_API_KEY environment variable or create jellyfin_config.json")
            elif len(sys.argv) < 3:
                print("Usage: python3 manage_enhanced.py mosaic-start [channelId1] [channelId2] ...")
            else:
                result = manager.mosaic_manager.start_session(sys.argv[2:])
                if result:
                    print(f"✅ Mosaic started successfully!\nSession ID: {result['sessionId']}\nStream URL: {result['url']}")
                else:
                    print("❌ Failed to start mosaic.")

        elif command == "mosaic-stop":
            if not manager.mosaic_manager:
                print("❌ Mosaic manager not configured. Please set JELLYFIN_API_KEY environment variable or create jellyfin_config.json")
            elif len(sys.argv) != 3:
                print("Usage: python3 manage_enhanced.py mosaic-stop [session_id]")
            else:
                if manager.mosaic_manager.stop_session(sys.argv[2]):
                    print("✅ Mosaic stopped successfully.")
                else:
                    print("❌ Failed to stop mosaic.")

        elif command == "mosaic-list":
            if not manager.mosaic_manager:
                print("❌ Mosaic manager not configured. Please set JELLYFIN_API_KEY environment variable or create jellyfin_config.json")
            else:
                sessions = manager.mosaic_manager.list_sessions()
                if not sessions:
                    print("ℹ️ No active mosaic sessions.")
                else:
                    print("Active Mosaic Sessions:")
                    for session_id, url in sessions.items():
                        print(f"  - ID: {session_id}\n    URL: {url}")

        else:
            print(f"❌ Unknown command: {command}")
            print("Run 'python3 manage_enhanced.py' to see available commands")
    
    except KeyboardInterrupt:
        print("\n⚠️  Operation cancelled by user")
    
    except Exception as e:
        print(f"❌ Command failed: {e}")
        logger.error(f"Command '{command}' failed: {e}", exc_info=True)

if __name__ == "__main__":
    main()
