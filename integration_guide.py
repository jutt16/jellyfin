#!/usr/bin/env python3
"""
Integration Guide for Enhanced Jellyfin IPTV Manager
Complete integration of all SparkleTV features with existing IPTV Manager
"""

import asyncio
import logging
import sys
import os
from pathlib import Path

# Import all enhanced modules
from advanced_grouping import AdvancedGrouping, create_default_rules
from logo_enhancer import LogoEnhancer, IPTVLogoEnhancer
from stream_health_checker import StreamHealthChecker, IPTVHealthMonitor
from performance_optimizer import PerformanceOptimizer, IPTVPerformanceManager
from enhanced_web_ui import EnhancedWebUI, EnhancedIPTVManager

logger = logging.getLogger(__name__)

class IntegratedIPTVManager:
    """Fully integrated IPTV Manager with all SparkleTV features"""
    
    def __init__(self, original_iptv_manager):
        self.original_manager = original_iptv_manager
        
        # Initialize enhanced components
        self.grouping = AdvancedGrouping()
        self.logo_enhancer = IPTVLogoEnhancer(original_iptv_manager)
        self.health_monitor = IPTVHealthMonitor(original_iptv_manager)
        self.performance_manager = IPTVPerformanceManager(original_iptv_manager)
        self.enhanced_manager = EnhancedIPTVManager(original_iptv_manager)
        
        # Setup default grouping rules
        for rule in create_default_rules():
            self.grouping.add_custom_rule(rule)
        
        logger.info("Integrated IPTV Manager initialized with all SparkleTV features")
    
    async def start_all_services(self):
        """Start all enhanced services"""
        try:
            # Start performance optimization
            self.performance_manager.start_optimization()
            
            # Start enhanced web UI
            await self.enhanced_manager.start_enhanced_features()
            
            logger.info("All enhanced services started successfully")
            
        except Exception as e:
            logger.error(f"Failed to start enhanced services: {e}")
            raise
    
    async def stop_all_services(self):
        """Stop all enhanced services"""
        try:
            # Stop performance optimization
            self.performance_manager.stop_optimization()
            
            # Stop enhanced web UI
            await self.enhanced_manager.stop_enhanced_features()
            
            logger.info("All enhanced services stopped")
            
        except Exception as e:
            logger.error(f"Error stopping enhanced services: {e}")
    
    async def run_comprehensive_update(self, force=False):
        """Run update with all enhancements"""
        logger.info("Starting comprehensive IPTV update with all enhancements...")
        
        try:
            # 1. Run original update process
            self.original_manager.run_update(force=force)
            
            # 2. Get all parsed content
            config = self.original_manager.load_config()
            providers = config.get('providers', [])
            
            all_channels = []
            for provider in providers:
                if provider.get('enabled', True):
                    provider_name = provider.get('name', '')
                    
                    # Get M3U content
                    m3u_content = self.original_manager.download_m3u(provider_name)
                    if m3u_content:
                        # Parse with enhanced grouping
                        parsed_content = self.original_manager.parse_m3u_content(
                            m3u_content, provider, 
                            config.get('group_filters', {}),
                            config.get('channel_mapping', {})
                        )
                        
                        # Convert to channel list for processing
                        for category, channels in parsed_content.items():
                            for channel_name, channel_data in channels.items():
                                channel_data['provider'] = provider_name
                                channel_data['category'] = category
                                all_channels.append(channel_data)
            
            # 3. Apply advanced grouping
            logger.info("Applying advanced grouping...")
            grouped_channels = self.grouping.organize_channels(all_channels, strategy="smart")
            grouping_stats = self.grouping.get_grouping_statistics(grouped_channels)
            logger.info(f"Grouping completed: {grouping_stats['total_groups']} groups, "
                       f"{grouping_stats['total_channels']} channels")
            
            # 4. Enhance logos
            logger.info("Enhancing channel logos...")
            for provider in providers:
                if provider.get('enabled', True):
                    await self.logo_enhancer.enhance_provider_logos(provider.get('name', ''))
            
            # 5. Run health check
            logger.info("Running comprehensive health check...")
            health_reports = await self.health_monitor.monitor_all_providers()
            
            # 6. Generate comprehensive report
            report = {
                'update_timestamp': self.original_manager.get_current_timestamp(),
                'providers_processed': len([p for p in providers if p.get('enabled', True)]),
                'total_channels': len(all_channels),
                'grouping_statistics': grouping_stats,
                'health_summary': self._summarize_health_reports(health_reports),
                'performance_status': self.performance_manager.get_optimization_status()
            }
            
            logger.info("Comprehensive update completed successfully")
            logger.info(f"Report: {report}")
            
            return report
            
        except Exception as e:
            logger.error(f"Comprehensive update failed: {e}")
            raise
    
    def _summarize_health_reports(self, health_reports):
        """Summarize health check results"""
        summary = {
            'total_providers': len(health_reports),
            'healthy_providers': 0,
            'total_channels_checked': 0,
            'online_channels': 0
        }
        
        for provider_name, report in health_reports.items():
            if 'error' not in report:
                summary['healthy_providers'] += 1
                health_data = report.get('health_report', {})
                summary['total_channels_checked'] += health_data.get('summary', {}).get('total_channels', 0)
                summary['online_channels'] += health_data.get('summary', {}).get('online_channels', 0)
        
        if summary['total_channels_checked'] > 0:
            summary['overall_success_rate'] = (summary['online_channels'] / summary['total_channels_checked']) * 100
        else:
            summary['overall_success_rate'] = 0
        
        return summary
    
    def get_integration_status(self):
        """Get status of all integrated components"""
        return {
            'grouping': {
                'enabled': True,
                'custom_rules': len(self.grouping.custom_rules),
                'available_strategies': ['smart', 'country', 'category', 'quality']
            },
            'logo_enhancement': {
                'enabled': True,
                'cache_stats': self.logo_enhancer.logo_enhancer.get_logo_statistics()
            },
            'health_monitoring': {
                'enabled': True,
                'checker_available': True
            },
            'performance_optimization': {
                'enabled': True,
                'monitoring_active': self.performance_manager.optimizer.monitoring_active,
                'current_profile': self.performance_manager.optimizer.current_profile.name if self.performance_manager.optimizer.current_profile else None
            },
            'enhanced_web_ui': {
                'enabled': True,
                'port': self.enhanced_manager.web_ui.port,
                'websocket_clients': len(self.enhanced_manager.web_ui.websockets)
            }
        }

def integrate_with_existing_manager():
    """Integration function for existing IPTV Manager"""
    
    # Import the existing IPTV Manager
    try:
        from iptv_manager import MultiProviderM3UConverter, IPTVManager
        
        # Create original manager instance
        original_converter = MultiProviderM3UConverter()
        original_manager = IPTVManager()
        original_manager.converter = original_converter
        
        # Create integrated manager
        integrated_manager = IntegratedIPTVManager(original_manager)
        
        return integrated_manager
        
    except ImportError as e:
        logger.error(f"Failed to import existing IPTV Manager: {e}")
        raise

async def main():
    """Main integration example"""
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    try:
        # Create integrated manager
        integrated_manager = integrate_with_existing_manager()
        
        # Start all services
        await integrated_manager.start_all_services()
        
        print("🚀 Enhanced Jellyfin IPTV Manager started successfully!")
        print(f"📊 Web Dashboard: http://localhost:8765")
        print(f"🔧 Recent Channels Plugin: Install RecentChannelsPlugin to Jellyfin")
        
        # Show integration status
        status = integrated_manager.get_integration_status()
        print("\n📋 Integration Status:")
        for component, details in status.items():
            enabled = "✅" if details.get('enabled') else "❌"
            print(f"  {enabled} {component.replace('_', ' ').title()}")
        
        # Run a comprehensive update
        print("\n🔄 Running comprehensive update...")
        report = await integrated_manager.run_comprehensive_update()
        
        print(f"\n📈 Update Summary:")
        print(f"  • Providers: {report['providers_processed']}")
        print(f"  • Channels: {report['total_channels']}")
        print(f"  • Groups: {report['grouping_statistics']['total_groups']}")
        print(f"  • Health: {report['health_summary']['overall_success_rate']:.1f}% success rate")
        
        print("\n🎯 All features are now active!")
        print("Press Ctrl+C to stop...")
        
        # Keep running
        while True:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
        await integrated_manager.stop_all_services()
        print("✅ Shutdown complete")
        
    except Exception as e:
        logger.error(f"Integration failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
