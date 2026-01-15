#!/usr/bin/env python3
"""
Setup Script for Enhanced Jellyfin IPTV Manager
Automated installation and configuration for all components
"""

import os
import sys
import json
import subprocess
import shutil
from pathlib import Path
import argparse
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class JellyfinIPTVSetup:
    """Automated setup for Enhanced Jellyfin IPTV Manager"""
    
    def __init__(self):
        self.script_dir = Path(__file__).parent
        self.is_synology = self.detect_synology()
        self.jellyfin_data_dir = self.detect_jellyfin_data_dir()
        self.setup_paths()
    
    def detect_synology(self):
        """Detect if running on Synology NAS"""
        return os.path.exists('/usr/syno') or 'synology' in os.uname().release.lower()
    
    def detect_jellyfin_data_dir(self):
        """Detect Jellyfin data directory"""
        possible_paths = [
            '/volume1/@appdata/jellyfin',
            '/volume2/@appdata/jellyfin',
            '/var/lib/jellyfin',
            '/config',  # Docker
            os.path.expanduser('~/.local/share/jellyfin'),  # Linux user install
            os.path.expanduser('~/AppData/Roaming/Jellyfin'),  # Windows
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                return Path(path)
        
        return None
    
    def setup_paths(self):
        """Setup installation paths based on environment"""
        if self.is_synology:
            self.install_dir = Path('/volume1/docker/iptv-manager')
            self.content_dir = Path('/volume1/jellyfin/iptv-content')
            self.plugin_dir = self.jellyfin_data_dir / 'config/plugins' if self.jellyfin_data_dir else None
        else:
            self.install_dir = Path.home() / 'jellyfin-iptv'
            self.content_dir = Path.home() / 'jellyfin-content'
            self.plugin_dir = self.jellyfin_data_dir / 'plugins' if self.jellyfin_data_dir else None
    
    def check_dependencies(self):
        """Check and install Python dependencies"""
        logger.info("Checking Python dependencies...")
        
        required_packages = [
            'requests',
            'aiohttp',
            'aiohttp-cors',
            'psutil',
            'asyncio'
        ]
        
        missing_packages = []
        
        for package in required_packages:
            try:
                __import__(package.replace('-', '_'))
                logger.info(f"✅ {package} is installed")
            except ImportError:
                missing_packages.append(package)
                logger.warning(f"❌ {package} is missing")
        
        if missing_packages:
            logger.info("Installing missing packages...")
            try:
                subprocess.check_call([
                    sys.executable, '-m', 'pip', 'install'
                ] + missing_packages)
                logger.info("✅ All dependencies installed successfully")
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to install dependencies: {e}")
                return False
        
        return True
    
    def create_directories(self):
        """Create necessary directories"""
        logger.info("Creating directory structure...")
        
        directories = [
            self.install_dir,
            self.content_dir,
            self.content_dir / 'IPV-Live',
            self.content_dir / 'IPV-Movies',
            self.content_dir / 'IPV-Series',
            self.content_dir / 'IPV-Catchup',
        ]
        
        for directory in directories:
            try:
                directory.mkdir(parents=True, exist_ok=True)
                logger.info(f"✅ Created directory: {directory}")
                
                # Set permissions on Synology
                if self.is_synology:
                    os.system(f"sudo chown -R jellyfin:jellyfin {directory}")
                    os.system(f"sudo chmod -R 755 {directory}")
                    
            except Exception as e:
                logger.error(f"Failed to create directory {directory}: {e}")
                return False
        
        return True
    
    def install_scripts(self):
        """Install main scripts"""
        logger.info("Installing IPTV Manager scripts...")
        
        scripts = [
            'iptv_manager.py',
            'advanced_grouping.py',
            'logo_enhancer.py',
            'stream_health_checker.py',
            'performance_optimizer.py',
            'enhanced_web_ui.py',
            'integration_guide.py'
        ]
        
        for script in scripts:
            source = self.script_dir / script
            destination = self.install_dir / script
            
            if source.exists():
                try:
                    shutil.copy2(source, destination)
                    destination.chmod(0o755)
                    logger.info(f"✅ Installed: {script}")
                    
                    # Set ownership on Synology
                    if self.is_synology:
                        os.system(f"sudo chown jellyfin:jellyfin {destination}")
                        
                except Exception as e:
                    logger.error(f"Failed to install {script}: {e}")
                    return False
            else:
                logger.warning(f"Script not found: {script}")
        
        return True
    
    def install_plugin(self):
        """Install Recent Channels Plugin"""
        if not self.plugin_dir:
            logger.warning("Jellyfin data directory not found, skipping plugin installation")
            return True
        
        logger.info("Installing Recent Channels Plugin...")
        
        plugin_source = self.script_dir / 'RecentChannelsPlugin'
        plugin_dest = self.plugin_dir / 'RecentChannels_1.0.0.0'
        
        if not plugin_source.exists():
            logger.warning("Recent Channels Plugin source not found")
            return True
        
        try:
            # Build plugin if .csproj exists
            csproj_file = plugin_source / 'RecentChannelsPlugin.csproj'
            if csproj_file.exists():
                logger.info("Building Recent Channels Plugin...")
                result = subprocess.run([
                    'dotnet', 'build', str(csproj_file), 
                    '--configuration', 'Release'
                ], capture_output=True, text=True)
                
                if result.returncode == 0:
                    logger.info("✅ Plugin built successfully")
                    
                    # Copy built files
                    build_dir = plugin_source / 'bin/Release/net8.0'
                    if build_dir.exists():
                        plugin_dest.mkdir(parents=True, exist_ok=True)
                        shutil.copytree(build_dir, plugin_dest, dirs_exist_ok=True)
                        logger.info(f"✅ Plugin installed to: {plugin_dest}")
                        
                        # Set permissions on Synology
                        if self.is_synology:
                            os.system(f"sudo chown -R jellyfin:jellyfin {plugin_dest}")
                    else:
                        logger.error("Build output directory not found")
                        return False
                else:
                    logger.error(f"Plugin build failed: {result.stderr}")
                    return False
            else:
                logger.warning("Plugin project file not found, copying source files")
                plugin_dest.mkdir(parents=True, exist_ok=True)
                shutil.copytree(plugin_source, plugin_dest, dirs_exist_ok=True)
        
        except Exception as e:
            logger.error(f"Failed to install plugin: {e}")
            return False
        
        return True
    
    def create_config_template(self):
        """Create configuration template"""
        logger.info("Creating configuration template...")
        
        config_template = {
            "providers": [
                {
                    "name": "Provider1",
                    "enabled": True,
                    "type": "xtream",
                    "server_url": "http://your-provider.com:8080",
                    "username": "your_username",
                    "password": "your_password"
                }
            ],
            "proxy": {
                "enabled": True,
                "m3u_url": "http://localhost:34400/playlist.m3u8"
            },
            "output_directory": str(self.content_dir),
            "group_filters": {
                "exclude": ["XXX", "Adult"]
            },
            "epg_sources": [],
            "advanced_grouping": {
                "enabled": True,
                "strategy": "smart"
            },
            "logo_enhancement": {
                "enabled": True,
                "github_repos": [
                    "tv-logo/tv-logos",
                    "Tapiosinn/tv-logos"
                ]
            },
            "health_monitoring": {
                "enabled": True,
                "check_interval": 3600
            },
            "performance_optimization": {
                "enabled": True,
                "profile": "balanced"
            },
            "web_ui": {
                "enabled": True,
                "port": 8765,
                "host": "0.0.0.0"
            }
        }
        
        config_file = self.install_dir / 'm3u_config.json'
        
        try:
            with open(config_file, 'w') as f:
                json.dump(config_template, f, indent=2)
            logger.info(f"✅ Configuration template created: {config_file}")
            
            # Set ownership on Synology
            if self.is_synology:
                os.system(f"sudo chown jellyfin:jellyfin {config_file}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to create configuration: {e}")
            return False
    
    def create_systemd_service(self):
        """Create systemd service for automatic startup"""
        if self.is_synology:
            logger.info("Skipping systemd service creation on Synology (use Task Scheduler instead)")
            return True
        
        logger.info("Creating systemd service...")
        
        service_content = f"""[Unit]
Description=Enhanced Jellyfin IPTV Manager
After=network.target jellyfin.service
Wants=jellyfin.service

[Service]
Type=simple
User=jellyfin
Group=jellyfin
WorkingDirectory={self.install_dir}
ExecStart={sys.executable} {self.install_dir}/enhanced_web_ui.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""
        
        service_file = Path('/etc/systemd/system/jellyfin-iptv.service')
        
        try:
            with open(service_file, 'w') as f:
                f.write(service_content)
            
            # Enable and start service
            subprocess.run(['sudo', 'systemctl', 'daemon-reload'])
            subprocess.run(['sudo', 'systemctl', 'enable', 'jellyfin-iptv.service'])
            
            logger.info("✅ Systemd service created and enabled")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create systemd service: {e}")
            return False
    
    def setup_cron_jobs(self):
        """Setup cron jobs for automation"""
        logger.info("Setting up cron jobs...")
        
        cron_jobs = [
            f"0 3 * * * {sys.executable} {self.install_dir}/integration_guide.py --auto-update",
            f"0 * * * * {sys.executable} {self.install_dir}/stream_health_checker.py --monitor"
        ]
        
        try:
            # Get current crontab
            result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
            current_cron = result.stdout if result.returncode == 0 else ""
            
            # Add new jobs if not already present
            new_cron = current_cron
            for job in cron_jobs:
                if job not in current_cron:
                    new_cron += f"\n{job}"
            
            # Install new crontab
            if new_cron != current_cron:
                process = subprocess.Popen(['crontab', '-'], stdin=subprocess.PIPE, text=True)
                process.communicate(input=new_cron)
                
                if process.returncode == 0:
                    logger.info("✅ Cron jobs installed successfully")
                else:
                    logger.error("Failed to install cron jobs")
                    return False
            else:
                logger.info("✅ Cron jobs already configured")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to setup cron jobs: {e}")
            return False
    
    def run_setup(self, install_plugin=True, setup_automation=True):
        """Run complete setup process"""
        logger.info("🚀 Starting Enhanced Jellyfin IPTV Manager Setup")
        logger.info(f"Environment: {'Synology NAS' if self.is_synology else 'Generic Linux'}")
        logger.info(f"Install directory: {self.install_dir}")
        logger.info(f"Content directory: {self.content_dir}")
        
        steps = [
            ("Checking dependencies", self.check_dependencies),
            ("Creating directories", self.create_directories),
            ("Installing scripts", self.install_scripts),
            ("Creating configuration", self.create_config_template),
        ]
        
        if install_plugin:
            steps.append(("Installing plugin", self.install_plugin))
        
        if setup_automation:
            if not self.is_synology:
                steps.append(("Creating systemd service", self.create_systemd_service))
            steps.append(("Setting up cron jobs", self.setup_cron_jobs))
        
        # Execute setup steps
        for step_name, step_func in steps:
            logger.info(f"📋 {step_name}...")
            if not step_func():
                logger.error(f"❌ Setup failed at: {step_name}")
                return False
        
        logger.info("✅ Setup completed successfully!")
        self.print_next_steps()
        return True
    
    def print_next_steps(self):
        """Print next steps for user"""
        print("\n" + "="*60)
        print("🎉 SETUP COMPLETE!")
        print("="*60)
        print(f"📁 Installation directory: {self.install_dir}")
        print(f"📁 Content directory: {self.content_dir}")
        print(f"⚙️  Configuration file: {self.install_dir}/m3u_config.json")
        
        print("\n📋 NEXT STEPS:")
        print("1. Edit the configuration file with your IPTV provider details")
        print("2. Run the integration guide to start all services:")
        print(f"   python3 {self.install_dir}/integration_guide.py")
        print("3. Access the web dashboard at: http://localhost:8765")
        print("4. Configure Jellyfin libraries to use the content directory")
        
        if self.plugin_dir:
            print("5. Restart Jellyfin to load the Recent Channels plugin")
        
        print("\n🔧 CONFIGURATION:")
        print(f"   Edit: {self.install_dir}/m3u_config.json")
        print("   Add your IPTV provider credentials and settings")
        
        print("\n📖 DOCUMENTATION:")
        print(f"   Setup Guide: {self.script_dir}/README.md")
        print(f"   Deployment Guide: {self.script_dir}/DEPLOYMENT_GUIDE.md")
        
        print("\n🚀 START SERVICES:")
        print(f"   cd {self.install_dir}")
        print("   python3 integration_guide.py")
        
        print("="*60)

def main():
    parser = argparse.ArgumentParser(description='Setup Enhanced Jellyfin IPTV Manager')
    parser.add_argument('--no-plugin', action='store_true', help='Skip plugin installation')
    parser.add_argument('--no-automation', action='store_true', help='Skip automation setup')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    setup = JellyfinIPTVSetup()
    
    success = setup.run_setup(
        install_plugin=not args.no_plugin,
        setup_automation=not args.no_automation
    )
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
