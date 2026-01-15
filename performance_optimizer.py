#!/usr/bin/env python3
"""
Performance Optimizer for Jellyfin IPTV Manager
Dynamic resource optimization based on system capabilities and workload
"""

import os
import psutil
import asyncio
import logging
import json
import time
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor
import threading

logger = logging.getLogger(__name__)

@dataclass
class SystemMetrics:
    """System performance metrics"""
    cpu_percent: float
    memory_percent: float
    memory_available_gb: float
    disk_usage_percent: float
    network_io_mbps: float
    load_average: float
    active_connections: int
    timestamp: float

@dataclass
class OptimizationProfile:
    """Performance optimization profile"""
    name: str
    max_concurrent_streams: int
    max_concurrent_downloads: int
    cache_size_mb: int
    timeout_seconds: int
    retry_attempts: int
    batch_size: int
    memory_threshold: float
    cpu_threshold: float

class PerformanceOptimizer:
    """Dynamic performance optimization system"""
    
    def __init__(self):
        self.current_profile = None
        self.metrics_history = []
        self.optimization_profiles = self._create_default_profiles()
        self.monitoring_active = False
        self.monitoring_task = None
        self.optimization_callbacks = []
        
    def _create_default_profiles(self) -> Dict[str, OptimizationProfile]:
        """Create default optimization profiles"""
        return {
            'low_resource': OptimizationProfile(
                name='Low Resource',
                max_concurrent_streams=3,
                max_concurrent_downloads=2,
                cache_size_mb=50,
                timeout_seconds=15,
                retry_attempts=2,
                batch_size=5,
                memory_threshold=80.0,
                cpu_threshold=70.0
            ),
            'balanced': OptimizationProfile(
                name='Balanced',
                max_concurrent_streams=8,
                max_concurrent_downloads=5,
                cache_size_mb=200,
                timeout_seconds=10,
                retry_attempts=3,
                batch_size=10,
                memory_threshold=70.0,
                cpu_threshold=60.0
            ),
            'high_performance': OptimizationProfile(
                name='High Performance',
                max_concurrent_streams=20,
                max_concurrent_downloads=10,
                cache_size_mb=500,
                timeout_seconds=8,
                retry_attempts=4,
                batch_size=20,
                memory_threshold=60.0,
                cpu_threshold=50.0
            ),
            'server_grade': OptimizationProfile(
                name='Server Grade',
                max_concurrent_streams=50,
                max_concurrent_downloads=20,
                cache_size_mb=1000,
                timeout_seconds=5,
                retry_attempts=5,
                batch_size=50,
                memory_threshold=50.0,
                cpu_threshold=40.0
            )
        }
    
    def get_system_metrics(self) -> SystemMetrics:
        """Collect current system performance metrics"""
        try:
            # CPU metrics
            cpu_percent = psutil.cpu_percent(interval=1)
            
            # Memory metrics
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            memory_available_gb = memory.available / (1024**3)
            
            # Disk metrics
            disk = psutil.disk_usage('/')
            disk_usage_percent = disk.percent
            
            # Network metrics
            net_io = psutil.net_io_counters()
            network_io_mbps = (net_io.bytes_sent + net_io.bytes_recv) / (1024**2)
            
            # Load average (Unix-like systems)
            try:
                load_average = os.getloadavg()[0]
            except (OSError, AttributeError):
                load_average = cpu_percent / 100.0
            
            # Active connections
            try:
                active_connections = len(psutil.net_connections())
            except (psutil.AccessDenied, OSError):
                active_connections = 0
            
            return SystemMetrics(
                cpu_percent=cpu_percent,
                memory_percent=memory_percent,
                memory_available_gb=memory_available_gb,
                disk_usage_percent=disk_usage_percent,
                network_io_mbps=network_io_mbps,
                load_average=load_average,
                active_connections=active_connections,
                timestamp=time.time()
            )
            
        except Exception as e:
            logger.error(f"Failed to collect system metrics: {e}")
            return SystemMetrics(0, 0, 0, 0, 0, 0, 0, time.time())
    
    def analyze_system_capacity(self) -> Dict[str, Any]:
        """Analyze system capacity and recommend profile"""
        metrics = self.get_system_metrics()
        
        # Determine system class based on resources
        total_memory_gb = psutil.virtual_memory().total / (1024**3)
        cpu_count = psutil.cpu_count()
        
        # System classification
        if total_memory_gb >= 16 and cpu_count >= 8:
            system_class = 'server_grade'
        elif total_memory_gb >= 8 and cpu_count >= 4:
            system_class = 'high_performance'
        elif total_memory_gb >= 4 and cpu_count >= 2:
            system_class = 'balanced'
        else:
            system_class = 'low_resource'
        
        # Check current load
        if metrics.cpu_percent > 80 or metrics.memory_percent > 85:
            # System under stress, downgrade recommendation
            downgrade_map = {
                'server_grade': 'high_performance',
                'high_performance': 'balanced',
                'balanced': 'low_resource',
                'low_resource': 'low_resource'
            }
            recommended_profile = downgrade_map.get(system_class, 'low_resource')
            stress_level = 'high'
        elif metrics.cpu_percent > 60 or metrics.memory_percent > 70:
            stress_level = 'medium'
            recommended_profile = system_class
        else:
            stress_level = 'low'
            recommended_profile = system_class
        
        return {
            'system_class': system_class,
            'recommended_profile': recommended_profile,
            'stress_level': stress_level,
            'metrics': asdict(metrics),
            'resources': {
                'total_memory_gb': total_memory_gb,
                'cpu_count': cpu_count,
                'available_memory_gb': metrics.memory_available_gb
            }
        }
    
    def select_optimal_profile(self) -> OptimizationProfile:
        """Select optimal performance profile based on current conditions"""
        analysis = self.analyze_system_capacity()
        recommended_profile_name = analysis['recommended_profile']
        
        profile = self.optimization_profiles.get(recommended_profile_name)
        if not profile:
            profile = self.optimization_profiles['balanced']
        
        # Fine-tune profile based on current metrics
        profile = self._fine_tune_profile(profile, analysis['metrics'])
        
        return profile
    
    def _fine_tune_profile(self, profile: OptimizationProfile, 
                          metrics: Dict[str, Any]) -> OptimizationProfile:
        """Fine-tune profile based on real-time metrics"""
        tuned_profile = OptimizationProfile(**asdict(profile))
        
        cpu_percent = metrics.get('cpu_percent', 0)
        memory_percent = metrics.get('memory_percent', 0)
        
        # Adjust concurrent operations based on current load
        if cpu_percent > 70:
            tuned_profile.max_concurrent_streams = max(1, int(profile.max_concurrent_streams * 0.7))
            tuned_profile.max_concurrent_downloads = max(1, int(profile.max_concurrent_downloads * 0.7))
        elif cpu_percent < 30:
            tuned_profile.max_concurrent_streams = int(profile.max_concurrent_streams * 1.2)
            tuned_profile.max_concurrent_downloads = int(profile.max_concurrent_downloads * 1.2)
        
        # Adjust cache size based on available memory
        if memory_percent > 80:
            tuned_profile.cache_size_mb = max(10, int(profile.cache_size_mb * 0.5))
        elif memory_percent < 50:
            tuned_profile.cache_size_mb = int(profile.cache_size_mb * 1.5)
        
        # Adjust timeouts based on system responsiveness
        load_average = metrics.get('load_average', 1.0)
        if load_average > 2.0:
            tuned_profile.timeout_seconds = int(profile.timeout_seconds * 1.5)
        elif load_average < 0.5:
            tuned_profile.timeout_seconds = max(3, int(profile.timeout_seconds * 0.8))
        
        return tuned_profile
    
    def apply_profile(self, profile: OptimizationProfile):
        """Apply optimization profile to system"""
        self.current_profile = profile
        
        # Notify all registered callbacks
        for callback in self.optimization_callbacks:
            try:
                callback(profile)
            except Exception as e:
                logger.error(f"Optimization callback failed: {e}")
        
        logger.info(f"Applied optimization profile: {profile.name}")
        logger.debug(f"Profile settings: {asdict(profile)}")
    
    def register_optimization_callback(self, callback):
        """Register callback for profile changes"""
        self.optimization_callbacks.append(callback)
    
    def start_monitoring(self, interval: int = 30):
        """Start continuous performance monitoring"""
        if self.monitoring_active:
            return
        
        self.monitoring_active = True
        self.monitoring_task = asyncio.create_task(self._monitoring_loop(interval))
        logger.info(f"Started performance monitoring (interval: {interval}s)")
    
    def stop_monitoring(self):
        """Stop performance monitoring"""
        self.monitoring_active = False
        if self.monitoring_task:
            self.monitoring_task.cancel()
        logger.info("Stopped performance monitoring")
    
    async def _monitoring_loop(self, interval: int):
        """Continuous monitoring loop"""
        try:
            while self.monitoring_active:
                # Collect metrics
                metrics = self.get_system_metrics()
                self.metrics_history.append(metrics)
                
                # Keep only last 100 metrics (about 50 minutes at 30s interval)
                if len(self.metrics_history) > 100:
                    self.metrics_history.pop(0)
                
                # Check if profile adjustment is needed
                optimal_profile = self.select_optimal_profile()
                
                if (not self.current_profile or 
                    optimal_profile.name != self.current_profile.name or
                    self._significant_change(optimal_profile)):
                    
                    self.apply_profile(optimal_profile)
                
                await asyncio.sleep(interval)
                
        except asyncio.CancelledError:
            logger.info("Performance monitoring cancelled")
        except Exception as e:
            logger.error(f"Performance monitoring error: {e}")
    
    def _significant_change(self, new_profile: OptimizationProfile) -> bool:
        """Check if profile change is significant enough to apply"""
        if not self.current_profile:
            return True
        
        # Check for significant changes in key parameters
        current = self.current_profile
        
        changes = [
            abs(new_profile.max_concurrent_streams - current.max_concurrent_streams) > 2,
            abs(new_profile.max_concurrent_downloads - current.max_concurrent_downloads) > 1,
            abs(new_profile.cache_size_mb - current.cache_size_mb) > 50,
            abs(new_profile.timeout_seconds - current.timeout_seconds) > 2
        ]
        
        return any(changes)
    
    def get_performance_report(self) -> Dict[str, Any]:
        """Generate performance analysis report"""
        if not self.metrics_history:
            return {'error': 'No metrics history available'}
        
        recent_metrics = self.metrics_history[-10:]  # Last 10 measurements
        
        # Calculate averages
        avg_cpu = sum(m.cpu_percent for m in recent_metrics) / len(recent_metrics)
        avg_memory = sum(m.memory_percent for m in recent_metrics) / len(recent_metrics)
        avg_load = sum(m.load_average for m in recent_metrics) / len(recent_metrics)
        
        # Find peaks
        max_cpu = max(m.cpu_percent for m in recent_metrics)
        max_memory = max(m.memory_percent for m in recent_metrics)
        
        # System analysis
        analysis = self.analyze_system_capacity()
        
        report = {
            'current_profile': asdict(self.current_profile) if self.current_profile else None,
            'system_analysis': analysis,
            'performance_metrics': {
                'average_cpu_percent': avg_cpu,
                'average_memory_percent': avg_memory,
                'average_load': avg_load,
                'peak_cpu_percent': max_cpu,
                'peak_memory_percent': max_memory,
                'metrics_collected': len(self.metrics_history)
            },
            'recommendations': self._generate_recommendations(analysis, recent_metrics),
            'monitoring_active': self.monitoring_active,
            'timestamp': time.time()
        }
        
        return report
    
    def _generate_recommendations(self, analysis: Dict[str, Any], 
                                recent_metrics: List[SystemMetrics]) -> List[str]:
        """Generate performance recommendations"""
        recommendations = []
        
        avg_cpu = sum(m.cpu_percent for m in recent_metrics) / len(recent_metrics)
        avg_memory = sum(m.memory_percent for m in recent_metrics) / len(recent_metrics)
        
        if avg_cpu > 80:
            recommendations.append("High CPU usage detected. Consider reducing concurrent operations.")
        
        if avg_memory > 85:
            recommendations.append("High memory usage detected. Consider reducing cache size.")
        
        if analysis['stress_level'] == 'high':
            recommendations.append("System under stress. Consider upgrading hardware or reducing workload.")
        
        if analysis['resources']['total_memory_gb'] < 4:
            recommendations.append("Low system memory. Consider adding more RAM for better performance.")
        
        if analysis['resources']['cpu_count'] < 4:
            recommendations.append("Limited CPU cores. Consider upgrading to a multi-core processor.")
        
        if not recommendations:
            recommendations.append("System performance is optimal.")
        
        return recommendations
    
    def optimize_for_task(self, task_type: str, **kwargs) -> Dict[str, Any]:
        """Optimize settings for specific task types"""
        current_metrics = self.get_system_metrics()
        
        if task_type == 'stream_checking':
            # Optimize for parallel stream health checking
            max_concurrent = min(50, max(5, int(100 - current_metrics.cpu_percent)))
            timeout = 10 if current_metrics.cpu_percent < 50 else 15
            
            return {
                'max_concurrent': max_concurrent,
                'timeout': timeout,
                'batch_size': max_concurrent // 2
            }
        
        elif task_type == 'logo_enhancement':
            # Optimize for logo downloading
            max_concurrent = min(10, max(2, int(50 - current_metrics.cpu_percent / 2)))
            
            return {
                'max_concurrent': max_concurrent,
                'timeout': 15,
                'cache_size_mb': min(100, max(10, int(current_metrics.memory_available_gb * 10)))
            }
        
        elif task_type == 'm3u_processing':
            # Optimize for M3U parsing and processing
            batch_size = min(1000, max(100, int(1000 - current_metrics.memory_percent * 5)))
            
            return {
                'batch_size': batch_size,
                'memory_limit_mb': int(current_metrics.memory_available_gb * 100),
                'use_threading': current_metrics.cpu_percent < 60
            }
        
        else:
            # Default optimization
            return {
                'max_concurrent': 5,
                'timeout': 10,
                'batch_size': 10
            }

# Integration with IPTV Manager
class IPTVPerformanceManager:
    """Performance management integration for IPTV Manager"""
    
    def __init__(self, iptv_manager):
        self.iptv_manager = iptv_manager
        self.optimizer = PerformanceOptimizer()
        self.setup_optimization_callbacks()
    
    def setup_optimization_callbacks(self):
        """Setup callbacks to apply optimizations to IPTV Manager"""
        def apply_to_iptv_manager(profile: OptimizationProfile):
            # Apply optimizations to various IPTV Manager components
            if hasattr(self.iptv_manager, 'health_manager'):
                self.iptv_manager.health_manager.max_concurrent = profile.max_concurrent_streams
                self.iptv_manager.health_manager.timeout = profile.timeout_seconds
            
            # Update download settings
            if hasattr(self.iptv_manager, 'converter'):
                self.iptv_manager.converter.max_retries = profile.retry_attempts
                self.iptv_manager.converter.timeout = profile.timeout_seconds
        
        self.optimizer.register_optimization_callback(apply_to_iptv_manager)
    
    def start_optimization(self):
        """Start performance optimization"""
        # Apply initial optimal profile
        optimal_profile = self.optimizer.select_optimal_profile()
        self.optimizer.apply_profile(optimal_profile)
        
        # Start monitoring
        self.optimizer.start_monitoring(interval=60)  # Check every minute
        
        logger.info("IPTV Performance optimization started")
    
    def stop_optimization(self):
        """Stop performance optimization"""
        self.optimizer.stop_monitoring()
        logger.info("IPTV Performance optimization stopped")
    
    def get_optimization_status(self) -> Dict[str, Any]:
        """Get current optimization status"""
        return self.optimizer.get_performance_report()

# Example usage
def main():
    """Example usage of performance optimizer"""
    optimizer = PerformanceOptimizer()
    
    # Analyze system
    analysis = optimizer.analyze_system_capacity()
    print(f"System Analysis: {json.dumps(analysis, indent=2, default=str)}")
    
    # Select and apply optimal profile
    profile = optimizer.select_optimal_profile()
    optimizer.apply_profile(profile)
    print(f"Applied Profile: {profile.name}")
    
    # Get performance report
    report = optimizer.get_performance_report()
    print(f"Performance Report: {json.dumps(report, indent=2, default=str)}")

if __name__ == "__main__":
    main()
