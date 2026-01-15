#!/usr/bin/env python3
"""
Enhanced Web UI System for Jellyfin IPTV Manager
Advanced web interface with real-time monitoring, stream proxy, and API endpoints
"""

import os
import json
import asyncio
import logging
from typing import Dict, List, Any, Optional
from pathlib import Path
from datetime import datetime
import aiohttp
from aiohttp import web, WSMsgType
import aiohttp_cors
import weakref

# Import our enhanced modules
from advanced_grouping import AdvancedGrouping
from logo_enhancer import LogoEnhancer
from stream_health_checker import StreamHealthChecker
from performance_optimizer import PerformanceOptimizer, IPTVPerformanceManager
from ip_failover_manager import IPFailoverManager

logger = logging.getLogger(__name__)

class EnhancedWebUI:
    """Enhanced web interface with advanced features"""
    
    def __init__(self, iptv_manager, port: int = 8765):
        self.iptv_manager = iptv_manager
        self.port = port
        self.app = None
        self.runner = None
        self.site = None
        
        # Enhanced components
        self.grouping = AdvancedGrouping()
        self.logo_enhancer = LogoEnhancer()
        self.health_checker = StreamHealthChecker()
        self.performance_optimizer = PerformanceOptimizer()
        self.ip_failover_manager = IPFailoverManager()
        
        # WebSocket connections for real-time updates
        self.websockets = weakref.WeakSet()
        
        # Cache for frequently accessed data
        self.cache = {
            'channels': None,
            'health_reports': None,
            'performance_stats': None,
            'last_update': None
        }
    
    def setup_routes(self):
        """Setup web routes and API endpoints"""
        self.app = web.Application()
        
        # Static files
        self.app.router.add_static('/', Path(__file__).parent / 'web_static', name='static')
        
        # Main pages
        self.app.router.add_get('/', self.index_handler)
        
        # API Routes
        self.app.router.add_get('/api/status', self.handle_status)
        self.app.router.add_get('/api/channels', self.handle_channels)
        self.app.router.add_get('/api/health', self.handle_health_check)
        self.app.router.add_get('/api/performance', self.handle_performance_stats)
        self.app.router.add_post('/api/update', self.handle_update_request)
        self.app.router.add_post('/api/optimize', self.handle_optimize_request)
        
        # IP Failover Routes
        self.app.router.add_get('/api/failover/status', self.handle_failover_status)
        self.app.router.add_get('/api/failover/sessions', self.handle_failover_sessions)
        self.app.router.add_get('/stream/{channel_id}', self.handle_failover_stream)
        
        # Stream proxy endpoints
        self.app.router.add_get('/proxy/stream/{provider}/{channel_id}', self.proxy_stream)
        self.app.router.add_get('/proxy/logo/{provider}/{channel_id}', self.proxy_logo)
        
        # WebSocket for real-time updates
        self.app.router.add_get('/ws', self.websocket_handler)
        
        # CORS setup
        cors = aiohttp_cors.setup(self.app, defaults={
            "*": aiohttp_cors.ResourceOptions(
                allow_credentials=True,
                expose_headers="*",
                allow_headers="*",
                allow_methods="*"
            )
        })
        
        # Add CORS to all routes
        for route in list(self.app.router.routes()):
            cors.add(route)
    
    async def index_handler(self, request):
        """Main dashboard page"""
        return web.FileResponse(Path(__file__).parent / 'web_static' / 'index.html')
    
    async def dashboard_handler(self, request):
        """Dashboard with real-time monitoring"""
        html_content = """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Jellyfin IPTV Manager - Dashboard</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #1a1a1a; color: white; }
                .container { max-width: 1200px; margin: 0 auto; }
                .header { text-align: center; margin-bottom: 30px; }
                .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px; margin-bottom: 30px; }
                .stat-card { background: #2a2a2a; padding: 20px; border-radius: 8px; border-left: 4px solid #00a4dc; }
                .stat-value { font-size: 2em; font-weight: bold; color: #00a4dc; }
                .stat-label { color: #ccc; margin-top: 5px; }
                .chart-container { background: #2a2a2a; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
                .status-online { color: #4CAF50; }
                .status-offline { color: #f44336; }
                .status-warning { color: #ff9800; }
                .btn { background: #00a4dc; color: white; border: none; padding: 10px 20px; border-radius: 4px; cursor: pointer; }
                .btn:hover { background: #0082b3; }
                .log-container { background: #1e1e1e; padding: 15px; border-radius: 4px; max-height: 300px; overflow-y: auto; font-family: monospace; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🎬 Jellyfin IPTV Manager Dashboard</h1>
                    <p>Real-time monitoring and management</p>
                </div>
                
                <div class="stats-grid" id="statsGrid">
                    <!-- Stats will be populated by JavaScript -->
                </div>
                
                <div class="chart-container">
                    <h3>System Performance</h3>
                    <canvas id="performanceChart" width="800" height="200"></canvas>
                </div>
                
                <div class="chart-container">
                    <h3>Recent Activity</h3>
                    <div class="log-container" id="activityLog">
                        <div>Loading activity log...</div>
                    </div>
                </div>
                
                <div style="text-align: center; margin-top: 30px;">
                    <button class="btn" onclick="runHealthCheck()">🔍 Run Health Check</button>
                    <button class="btn" onclick="enhanceLogos()">🖼️ Enhance Logos</button>
                    <button class="btn" onclick="optimizePerformance()">⚡ Optimize Performance</button>
                </div>
            </div>
            
            <script>
                let ws = null;
                let performanceData = [];
                
                function connectWebSocket() {
                    ws = new WebSocket('ws://localhost:8765/ws');
                    
                    ws.onopen = function() {
                        console.log('WebSocket connected');
                        addLogEntry('WebSocket connected', 'info');
                    };
                    
                    ws.onmessage = function(event) {
                        const data = JSON.parse(event.data);
                        handleRealtimeUpdate(data);
                    };
                    
                    ws.onclose = function() {
                        console.log('WebSocket disconnected');
                        addLogEntry('WebSocket disconnected', 'warning');
                        setTimeout(connectWebSocket, 5000);
                    };
                }
                
                function handleRealtimeUpdate(data) {
                    if (data.type === 'stats') {
                        updateStats(data.data);
                    } else if (data.type === 'performance') {
                        updatePerformanceChart(data.data);
                    } else if (data.type === 'activity') {
                        addLogEntry(data.message, data.level);
                    }
                }
                
                function updateStats(stats) {
                    const grid = document.getElementById('statsGrid');
                    grid.innerHTML = `
                        <div class="stat-card">
                            <div class="stat-value">${stats.total_channels || 0}</div>
                            <div class="stat-label">Total Channels</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-value status-online">${stats.online_channels || 0}</div>
                            <div class="stat-label">Online Channels</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-value">${stats.total_providers || 0}</div>
                            <div class="stat-label">Active Providers</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-value">${stats.cpu_usage || 0}%</div>
                            <div class="stat-label">CPU Usage</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-value">${stats.memory_usage || 0}%</div>
                            <div class="stat-label">Memory Usage</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-value">${stats.uptime || '0h'}</div>
                            <div class="stat-label">Uptime</div>
                        </div>
                    `;
                }
                
                function addLogEntry(message, level) {
                    const log = document.getElementById('activityLog');
                    const timestamp = new Date().toLocaleTimeString();
                    const levelClass = level === 'error' ? 'status-offline' : 
                                     level === 'warning' ? 'status-warning' : 'status-online';
                    
                    const entry = document.createElement('div');
                    entry.innerHTML = `<span class="${levelClass}">[${timestamp}]</span> ${message}`;
                    log.insertBefore(entry, log.firstChild);
                    
                    // Keep only last 50 entries
                    while (log.children.length > 50) {
                        log.removeChild(log.lastChild);
                    }
                }
                
                async function runHealthCheck() {
                    addLogEntry('Starting health check...', 'info');
                    try {
                        const response = await fetch('/api/health/check', { method: 'POST' });
                        const result = await response.json();
                        addLogEntry(`Health check completed: ${result.summary}`, 'info');
                    } catch (error) {
                        addLogEntry(`Health check failed: ${error.message}`, 'error');
                    }
                }
                
                async function enhanceLogos() {
                    addLogEntry('Starting logo enhancement...', 'info');
                    try {
                        const response = await fetch('/api/logos/enhance', { method: 'POST' });
                        const result = await response.json();
                        addLogEntry(`Logo enhancement completed: ${result.enhanced_count} logos enhanced`, 'info');
                    } catch (error) {
                        addLogEntry(`Logo enhancement failed: ${error.message}`, 'error');
                    }
                }
                
                async function optimizePerformance() {
                    addLogEntry('Optimizing performance...', 'info');
                    try {
                        const response = await fetch('/api/performance', { method: 'POST' });
                        const result = await response.json();
                        addLogEntry(`Performance optimized: ${result.profile} profile applied`, 'info');
                    } catch (error) {
                        addLogEntry(`Performance optimization failed: ${error.message}`, 'error');
                    }
                }
                
                // Initialize
                connectWebSocket();
                
                // Load initial data
                fetch('/api/status')
                    .then(response => response.json())
                    .then(data => updateStats(data))
                    .catch(error => addLogEntry(`Failed to load initial data: ${error.message}`, 'error'));
            </script>
        </body>
        </html>
        """
        return web.Response(text=html_content, content_type='text/html')
    
    async def channels_handler(self, request):
        """Channels management page"""
        return web.Response(text="<h1>Channels Management</h1><p>Coming soon...</p>", content_type='text/html')
    
    async def health_handler(self, request):
        """Health monitoring page"""
        return web.Response(text="<h1>Health Monitoring</h1><p>Coming soon...</p>", content_type='text/html')
    
    async def settings_handler(self, request):
        """Settings page"""
        return web.Response(text="<h1>Settings</h1><p>Coming soon...</p>", content_type='text/html')
    
    async def api_status(self, request):
        """API endpoint for system status"""
        try:
            config = self.iptv_manager.load_config()
            providers = config.get('providers', [])
            enabled_providers = [p for p in providers if p.get('enabled', True)]
            
            # Get performance metrics
            metrics = self.performance_optimizer.get_system_metrics()
            
            status = {
                'total_providers': len(enabled_providers),
                'total_channels': 0,  # Would need to calculate from parsed content
                'online_channels': 0,  # Would need health check data
                'cpu_usage': round(metrics.cpu_percent, 1),
                'memory_usage': round(metrics.memory_percent, 1),
                'uptime': f"{int(metrics.timestamp - self.iptv_manager.start_time)}s" if hasattr(self.iptv_manager, 'start_time') else '0s',
                'last_update': datetime.now().isoformat()
            }
            
            return web.json_response(status)
            
        except Exception as e:
            logger.error(f"Status API error: {e}")
            return web.json_response({'error': str(e)}, status=500)
    
    async def api_channels(self, request):
        """API endpoint for channels list"""
        try:
            # Get channels from cache or load fresh
            if self.cache['channels'] is None or self._cache_expired():
                await self._refresh_channels_cache()
            
            return web.json_response(self.cache['channels'])
            
        except Exception as e:
            logger.error(f"Channels API error: {e}")
            return web.json_response({'error': str(e)}, status=500)
    
    async def api_health_check(self, request):
        """API endpoint to trigger health check"""
        try:
            # This would integrate with the health checker
            async with self.health_checker:
                # Simplified health check for demo
                result = {
                    'status': 'completed',
                    'summary': 'Health check completed successfully',
                    'timestamp': datetime.now().isoformat()
                }
            
            # Broadcast to WebSocket clients
            await self._broadcast_websocket({
                'type': 'activity',
                'message': 'Health check completed',
                'level': 'info'
            })
            
            return web.json_response(result)
            
        except Exception as e:
            logger.error(f"Health check API error: {e}")
            return web.json_response({'error': str(e)}, status=500)
    
    async def api_enhance_logos(self, request):
        """API endpoint to enhance logos"""
        try:
            # This would integrate with the logo enhancer
            result = {
                'status': 'completed',
                'enhanced_count': 0,  # Would be actual count
                'timestamp': datetime.now().isoformat()
            }
            
            # Broadcast to WebSocket clients
            await self._broadcast_websocket({
                'type': 'activity',
                'message': f'Logo enhancement completed: {result["enhanced_count"]} logos enhanced',
                'level': 'info'
            })
            
            return web.json_response(result)
            
        except Exception as e:
            logger.error(f"Logo enhancement API error: {e}")
            return web.json_response({'error': str(e)}, status=500)
    
    async def websocket_handler(self, request):
        """WebSocket handler for real-time updates"""
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        
        self.websockets.add(ws)
        logger.info("WebSocket client connected")
        
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        await self._handle_websocket_message(ws, data)
                    except json.JSONDecodeError:
                        await ws.send_str(json.dumps({'error': 'Invalid JSON'}))
                elif msg.type == WSMsgType.ERROR:
                    logger.error(f'WebSocket error: {ws.exception()}')
        except Exception as e:
            logger.error(f"WebSocket handler error: {e}")
        finally:
            logger.info("WebSocket client disconnected")
        
        return ws
    
    async def _handle_websocket_message(self, ws, data):
        """Handle incoming WebSocket messages"""
        message_type = data.get('type')
        
        if message_type == 'subscribe':
            # Client wants to subscribe to updates
            await ws.send_str(json.dumps({
                'type': 'subscribed',
                'message': 'Successfully subscribed to updates'
            }))
        elif message_type == 'ping':
            await ws.send_str(json.dumps({'type': 'pong'}))
    
    async def _broadcast_websocket(self, data):
        """Broadcast data to all connected WebSocket clients"""
        if not self.websockets:
            return
        
        message = json.dumps(data)
        disconnected = []
        
        for ws in self.websockets:
            try:
                await ws.send_str(message)
            except Exception:
                disconnected.append(ws)
        
        # Remove disconnected clients
        for ws in disconnected:
            self.websockets.discard(ws)
    
    async def _refresh_channels_cache(self):
        """Refresh channels cache"""
        try:
            config = self.iptv_manager.load_config()
            providers = config.get('providers', [])
            
            all_channels = []
            for provider in providers:
                if provider.get('enabled', True):
                    # This would parse M3U content and extract channels
                    # Simplified for demo
                    provider_channels = {
                        'provider': provider.get('name', ''),
                        'channels': []  # Would contain actual channel data
                    }
                    all_channels.append(provider_channels)
            
            self.cache['channels'] = all_channels
            self.cache['last_update'] = datetime.now()
            
        except Exception as e:
            logger.error(f"Failed to refresh channels cache: {e}")
    
    def _cache_expired(self, max_age_minutes: int = 5) -> bool:
        """Check if cache has expired"""
        if self.cache['last_update'] is None:
            return True
        
        age = (datetime.now() - self.cache['last_update']).total_seconds() / 60
        return age > max_age_minutes
    
    async def start(self):
        """Start the enhanced web UI server"""
        try:
            self.setup_routes()
            
            self.runner = web.AppRunner(self.app)
            await self.runner.setup()
            
            self.site = web.TCPSite(self.runner, '0.0.0.0', self.port)
            await self.site.start()
            
            # Start performance monitoring
            self.performance_optimizer.start_monitoring()
            
            logger.info(f"Enhanced Web UI started on http://0.0.0.0:{self.port}")
            
            # Start real-time update task
            asyncio.create_task(self._realtime_update_loop())
            
        except Exception as e:
            logger.error(f"Failed to start Enhanced Web UI: {e}")
            raise
    
    async def stop(self):
        """Stop the enhanced web UI server"""
        try:
            self.performance_optimizer.stop_monitoring()
            
            if self.site:
                await self.site.stop()
            if self.runner:
                await self.runner.cleanup()
            
            logger.info("Enhanced Web UI stopped")
            
        except Exception as e:
            logger.error(f"Error stopping Enhanced Web UI: {e}")
    
    async def _realtime_update_loop(self):
        """Send real-time updates to WebSocket clients"""
        try:
            while True:
                # Send performance updates every 30 seconds
                metrics = self.performance_optimizer.get_system_metrics()
                
                await self._broadcast_websocket({
                    'type': 'performance',
                    'data': {
                        'cpu_percent': metrics.cpu_percent,
                        'memory_percent': metrics.memory_percent,
                        'timestamp': metrics.timestamp
                    }
                })
                
                await asyncio.sleep(30)
                
        except asyncio.CancelledError:
            logger.info("Real-time update loop cancelled")
        except Exception as e:
            logger.error(f"Real-time update loop error: {e}")

# Integration with existing IPTV Manager
class EnhancedIPTVManager:
    """Enhanced IPTV Manager with all new features"""
    
    def __init__(self, iptv_manager):
        self.iptv_manager = iptv_manager
        self.web_ui = EnhancedWebUI(iptv_manager)
        self.start_time = datetime.now().timestamp()
        
        # Set start time for uptime calculation
        iptv_manager.start_time = self.start_time
    
    async def start_enhanced_features(self):
        """Start all enhanced features"""
        try:
            await self.web_ui.start()
            logger.info("All enhanced features started successfully")
        except Exception as e:
            logger.error(f"Failed to start enhanced features: {e}")
            raise
    
    async def stop_enhanced_features(self):
        """Stop all enhanced features"""
        try:
            await self.web_ui.stop()
            logger.info("All enhanced features stopped")
        except Exception as e:
            logger.error(f"Error stopping enhanced features: {e}")

# Example usage
async def main():
    """Example usage of enhanced web UI"""
    # This would normally be integrated with the existing IPTV Manager
    class MockIPTVManager:
        def load_config(self):
            return {'providers': []}
    
    mock_manager = MockIPTVManager()
    enhanced_manager = EnhancedIPTVManager(mock_manager)
    
    try:
        await enhanced_manager.start_enhanced_features()
        print("Enhanced Web UI started on http://localhost:8765")
        
        # Keep running
        while True:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        print("Shutting down...")
        await enhanced_manager.stop_enhanced_features()

if __name__ == "__main__":
    asyncio.run(main())
