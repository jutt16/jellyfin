# IPTV Manager Deployment Guide for Synology NAS + Jellyfin

This guide will help you deploy the IPTV Manager script on your Synology NAS with Jellyfin already installed via SynoCommunity.

## Prerequisites

- ✅ Synology NAS with DSM 7.0+
- ✅ Jellyfin installed via SynoCommunity package
- ✅ SSH access enabled on your Synology NAS
- ✅ IPTV provider credentials (M3U URL or Xtream API details)
- ✅ Basic terminal/SSH knowledge

## Understanding Jellyfin Paths on Synology (SynoCommunity)

Before we begin, it's helpful to know where Jellyfin stores its files on a Synology NAS when installed from the SynoCommunity package source:

- **Application Binaries**: `/var/packages/jellyfin/target/`
  - This is where the core Jellyfin application files reside. You typically won't need to touch these.
- **Configuration & Data**: `/volume1/@appdata/jellyfin/` (or `/volumeX/@appdata/jellyfin/`)
  - This is the most important directory for management. It contains your libraries' metadata, system settings, plugins, and logs. This data is kept separate to survive application upgrades.

Our script and its media output will be stored separately for clean organization.

## Step 1: Prepare Your Synology Environment

### 1.1 Enable SSH Access
1. Open **DSM Control Panel** → **Terminal & SNMP**
2. Check **Enable SSH service**
3. Set port (default: 22) and click **Apply**

### 1.2 Connect via SSH
```bash
ssh admin@YOUR_NAS_IP
# Replace YOUR_NAS_IP with your actual NAS IP address
# Example: ssh admin@192.168.1.100
```

### 1.3 Install Python3 (if not already installed)
```bash
# Check if Python3 is installed
python3 --version

# If not installed, install via Package Center or command line
sudo synopkg install python3
```

## Step 2: Create Directory Structure

### 2.1 Create Main Directories
```bash
# Create the script directory
sudo mkdir -p /volume1/docker/iptv-manager
cd /volume1/docker/iptv-manager

# Create the media output directory
sudo mkdir -p /volume1/jellyfin/iptv-content

# Set proper permissions
sudo chown -R jellyfin:jellyfin /volume1/jellyfin/iptv-content
sudo chmod -R 755 /volume1/jellyfin/iptv-content
```

## Step 3: Deploy the Scripts

### 3.1 Download the Main IPTV Manager Script
```bash
# Navigate to script directory
cd /volume1/docker/iptv-manager

# Create the main IPTV manager script
sudo nano iptv_manager.py
```

**Copy and paste the entire `iptv_manager.py` script content into the nano editor, then save with `Ctrl+X`, `Y`, `Enter`**

### 3.2 Deploy the Enhanced Management Script
```bash
# Create the enhanced management script for enterprise monitoring
sudo nano manage_enhanced.py
```

**Copy and paste the entire `manage_enhanced.py` script content into the nano editor, then save with `Ctrl+X`, `Y`, `Enter`**

This enhanced script provides:
- **Async failover monitoring** with automatic service recovery
- **Service dependency management** with health verification
- **Redis cache optimization** and performance monitoring
- **Background monitoring** with enterprise-grade capabilities

### 3.3 Update Script Configuration for Synology
Both scripts come pre-configured with Synology-optimized paths:

**IPTV Manager (`iptv_manager.py`):**
```python
# --- Configuration ---
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "m3u_config.json")
LOG_FILE = os.path.join(SCRIPT_DIR, "iptv_manager.log")  # Keeps logs with script
BASE_DIR = "/volume1/jellyfin/iptv-content"  # Jellyfin media directory
LAST_UPDATE_FILE = os.path.join(SCRIPT_DIR, "m3u_last_update.json")  # Keeps with script
```

**Enhanced Manager (`manage_enhanced.py`):**
```python
# --- Configuration ---
self.base_dir = Path("/volume1/jellyfin-enhanced")
self.docker_services = ['threadfin-primary', 'iptv-proxy-failover', 'iptv-loadbalancer', ...]
self.failover_endpoints = {
    'load_balancer': 'http://127.0.0.1:34500',
    'threadfin': 'http://127.0.0.1:34400',
    'iptv_proxy': 'http://127.0.0.1:8080'
}
```

**Note**: These paths are optimized for Synology NAS but can be customized during the initial setup if needed.

### 3.4 Make Scripts Executable
```bash
# Make both scripts executable
sudo chmod +x iptv_manager.py
sudo chmod +x manage_enhanced.py

# Set proper ownership
sudo chown jellyfin:jellyfin iptv_manager.py
sudo chown jellyfin:jellyfin manage_enhanced.py
```

### 3.5 Install Required Python Packages
```bash
# Install required libraries for both scripts
sudo python3 -m pip install requests flask

# Optional packages (with fallbacks if unavailable):
sudo python3 -m pip install aiohttp redis psutil

# Note: 
# - flask is REQUIRED for the built-in web multichannel viewer
# - aiohttp is optional for async monitoring (fallback to requests)
# - redis is optional for caching (fallback to memory)
# - psutil is optional for system monitoring
```

## Step 4: Initial Configuration

### 4.1 Run Initial IPTV Setup
```bash
cd /volume1/docker/iptv-manager
sudo -u jellyfin python3 iptv_manager.py
```

### 4.2 Configure Proxy Settings (REQUIRED)
The IPTV manager requires a proxy (like Threadfin or iptv-proxy) for remote access:

```bash
# Run the IPTV manager
sudo -u jellyfin python3 iptv_manager.py

# From the menu, choose "2. Manage Proxy Settings (REQUIRED)"
# Enable proxy and enter your proxy M3U URL
```

### 4.3 Test Enhanced Management (Optional)
```bash
# Test the enhanced management script
sudo python3 manage_enhanced.py status

# Start async monitoring (enterprise feature)
sudo python3 manage_enhanced.py monitor

# Optimize Redis cache performance
sudo python3 manage_enhanced.py optimize-cache
```

### 4.4 Configure Your IPTV Provider
When the menu appears, choose **"1. Initial Setup / Add Providers"**

**For Xtream API providers:**
- Choose option **2** (Separate Xtream Credentials)
- Server URL: `http://your-provider.com:8080` (replace with your provider's server)
- Username: `your_username` (from your provider)
- Password: `your_password` (from your provider)

**For M3U URL providers:**
- Choose option **3** (Direct M3U URL)
- Enter your M3U URL: `http://your-provider.com/playlist.m3u`

### 4.5 Configure Output Directory
When prompted for output directory, use: `/volume1/jellyfin/iptv-content`

### 4.6 Configure EPG Sources (Optional but Recommended)
The script supports merging multiple EPG sources into a single, comprehensive guide.
- From the main menu, choose **"5. Manage EPG Sources"**.
- Add all your XMLTV EPG URLs, one by one. The script will download them all and merge them into a single `epg.xml` file during each update.
- Example: `http://your-provider.com/xmltv.php?username=XXX&password=XXX`

## Step 5: Test the Setup

### 5.1 Run a Test Update
From the main menu, choose **"10. Dry Run (simulate and report)"** to see what content would be processed without creating files.

### 5.2 Run First Update
Choose **"9. Run Update (force refresh)"** to generate all files for the first time. This ensures you get all content without waiting for the remote source to change.

### 5.3 Verify File Creation
```bash
# Check if files were created
ls -la /volume1/jellyfin/iptv-content/
# You should see directories: IPV-Live, IPV-Movies, IPV-Series, IPV-Catchup
# Plus files: IPV-Live_EPG.m3u, epg.xml, IPV_Merge_Report.txt
```

## Step 6: Configure Jellyfin

### 6.1 Add Media Libraries
1. Open **Jellyfin Web Interface** (usually `http://YOUR_NAS_IP:8096`)
2. Go to **Dashboard** → **Libraries**
3. Click **Add Media Library**

**For Movies:**
- Content Type: **Movies**
- Display Name: **IPTV Movies**
- Folders: Add `/volume1/jellyfin/iptv-content/IPV-Movies`

**For TV Shows:**
- Content Type: **Shows**
- Display Name: **IPTV Series**
- Folders: Add `/volume1/jellyfin/iptv-content/IPV-Series`

**For Live TV (Optional):**
- Content Type: **Mixed Movies & TV**
- Display Name: **IPTV Live**
- Folders: Add `/volume1/jellyfin/iptv-content/IPV-Live`

### 6.2 Configure Live TV & EPG
1. Go to **Dashboard** → **Live TV**
2. Click **Add** next to **Tuner Devices**
3. Select **M3U Tuner**
4. File or URL: `/volume1/jellyfin/iptv-content/IPV-Live_EPG.m3u`
5. Click **Save**

**Add EPG Source:**
1. In Live TV settings, click **Add** next to **TV Guide Data Providers**
2. Select **XMLTV**
3. File or URL: `/volume1/jellyfin/iptv-content/epg.xml`
4. Click **Save**

## Step 7: Automation & Monitoring

### 7.1 Set Up Automatic IPTV Updates
From the IPTV manager script menu, choose **"15. Setup Cron Automation"**
- Choose **"3. Daily at 3 AM"** for daily updates
- This will automatically update your content every day

### 7.2 Set Up Enterprise Monitoring (Recommended)
```bash
# Start continuous background monitoring
sudo python3 manage_enhanced.py monitor

# This provides:
# - Automatic service restart on failures
# - Real-time health monitoring
# - Cache optimization
# - Service dependency verification
```

### 7.3 Manual Cron Setup (Alternative)
```bash
# Edit crontab for jellyfin user
sudo crontab -u jellyfin -e

# Add this line for daily IPTV updates at 3 AM:
0 3 * * * /usr/bin/python3 /volume1/docker/iptv-manager/iptv_manager.py --auto-mode >> /volume1/docker/iptv-manager/iptv_manager.log 2>&1

# Add this line for hourly system monitoring:
0 * * * * /usr/bin/python3 /volume1/docker/iptv-manager/manage_enhanced.py status >> /volume1/docker/iptv-manager/monitoring.log 2>&1
```

## Step 8: Maintenance & Troubleshooting

### 8.1 Check Logs
```bash
# View IPTV manager log entries
tail -50 /volume1/docker/iptv-manager/iptv_manager.log

# View enhanced management logs
tail -50 /volume1/docker/iptv-manager/monitoring.log

# View merge report
cat /volume1/jellyfin/iptv-content/IPV_Merge_Report.txt
```

### 8.2 Monitor System Health
```bash
# Check comprehensive system status
sudo python3 manage_enhanced.py status

# Show detailed failover statistics
sudo python3 manage_enhanced.py stats

# Optimize cache performance
sudo python3 manage_enhanced.py optimize-cache
```

### 8.3 Update Content Manually
```bash
cd /volume1/docker/iptv-manager

# Update IPTV content
sudo -u jellyfin python3 iptv_manager.py
# Choose option 12 (Run Update Now) or 13 (Run Update (force refresh)) for updates

# Start async monitoring for automatic updates
sudo -u jellyfin python3 iptv_manager.py
# Choose option 11 (Start Async Failover Monitoring)

# Start built-in web multichannel viewer
sudo -u jellyfin python3 iptv_manager.py
# Choose option 16 (Start Web Multichannel Viewer)
# Choose option 17 (Stop Web Multichannel Viewer) to stop
```

### 8.4 Troubleshooting Jellyfin

If you suspect an issue with Jellyfin itself (not the script), you can investigate its configuration and data files directly:

- **Jellyfin Configuration**: Check files in `/volume1/@appdata/jellyfin/config/` to see how your libraries are configured.
- **Jellyfin Metadata/Cache**: Issues with artwork or metadata might be resolved by clearing items in `/volume1/@appdata/jellyfin/data/` and `/volume1/@appdata/jellyfin/cache/`.
- **Jellyfin Logs**: Check Jellyfin's own logs at `/volume1/@appdata/jellyfin/log/` for application-specific issues.

### 8.5 Common Script Issues & Solutions

**Issue: Permission denied errors**
```bash
sudo chown -R jellyfin:jellyfin /volume1/jellyfin/iptv-content
sudo chown -R jellyfin:jellyfin /volume1/docker/iptv-manager
```

**Issue: Python packages missing**
```bash
sudo python3 -m pip install requests
```

**Issue: Jellyfin not seeing files**
- Go to Jellyfin Dashboard → Libraries → [Your Library] → Scan Library.
- Verify that the `jellyfin` user has read/write permissions on the `/volume1/jellyfin/iptv-content` directory.
- Double-check that the folder paths in Jellyfin's library setup match exactly (e.g., `/volume1/jellyfin/iptv-content/IPV-Movies`).

### 8.6 Backup and Restore Configuration
Use the script menu to protect your settings.
- **Backup**: Choose **"7. Backup/Restore Configuration"** -> **"1. Backup Current Configuration"**. This saves your `m3u_config.json` to a timestamped file in the `backups` directory.
- **Restore**: Choose **"7. Backup/Restore Configuration"** -> **"2. Restore Configuration from Backup"**. Select a backup file to overwrite your current configuration. This is useful for migrating or recovering your setup.

## Step 9: Advanced Configuration

### 9.1 Group Filtering
Use the script menu option **"4. Manage Group Filters"** to exclude unwanted channel groups (e.g., adult content).

### 9.2 Multiple Providers
You can add multiple IPTV providers through the setup menu. The script will merge content and create failover playlists automatically.

### 9.3 Collections
The script automatically creates movie collections for franchises. Check `/volume1/jellyfin/iptv-content/IPV-Movies/Collections/` for organized movie series.

### 9.4 Advanced Channel Mapping
This feature gives you full control over your channel lineup.
- From the main menu, choose **"6. Advanced Channel Mapping"**.
- You can **Add/Edit** mappings to override a channel's name, group, or logo URL.
- This is perfect for renaming channels, grouping them logically, or fixing missing/incorrect logos.

## Step 10: Built-in Web Multichannel Viewer (Recommended)

The IPTV manager includes a built-in web-based multichannel viewer that eliminates the need for external apps. This viewer allows you to watch multiple IPTV channels simultaneously in a responsive grid layout directly in your web browser.

### 10.1 Features
- **Multiple Grid Layouts**: Single, 2x1, 2x2, 3x2, and 3x3 channel grids
- **Professional Streaming**: HLS.js integration for adaptive quality (ExoPlayer-like performance)
- **Easy Channel Selection**: Dropdown menus and searchable channel list
- **Cross-Platform**: Desktop, mobile, tablet, and Android TV browsers
- **Built-in Stream Proxy**: Automatic CORS handling and URL validation
- **Responsive Design**: Optimized for all screen sizes
- **No External Dependencies**: Uses only the existing IPTV manager script

### 10.2 Quick Start
1. **Configure Proxy**: Ensure proxy settings are configured (menu option 2)
2. **Generate Channel Data**: Run an IPTV update (menu option 12 or 13)
3. **Start Web Viewer**: From main menu, choose option 16 "Start Web Multichannel Viewer"
4. **Access Interface**: Open browser to `http://YOUR_NAS_IP:8765` (default port)
5. **Select Channels**: Use "Channel List" or dropdown menus in each grid slot
6. **Switch Layouts**: Use grid buttons (Single, 2x1, 2x2, 3x2, 3x3)

### 10.3 Network Access & Port Management
- **Local Access**: `http://localhost:8765`
- **Network Access**: `http://YOUR_NAS_IP:8765` (script auto-detects your IP)
- **Mobile/Tablet**: Same URLs work on all devices
- **Android TV**: Compatible with Android TV browsers
- **Custom Port**: Specify custom port when starting (handles conflicts automatically)
- **Status Check**: Menu shows current viewer status (Running/Stopped)

### 10.4 Advanced Features
- **Automatic Port Detection**: Finds available ports if default is in use
- **Graceful Shutdown**: Proper resource cleanup when stopping viewer
- **Error Recovery**: Robust error handling and stream failover
- **Stream Validation**: URL validation and proxy-based CORS handling
- **Background Operation**: Runs independently from main script menu

## Step 11: Jellyfin Plugin Integration (Optional)

The project includes a Jellyfin plugin that provides dashboard control over the web viewer and IPTV manager functions.

### 11.1 Plugin Features
- **Dashboard Integration**: Control web viewer from Jellyfin dashboard
- **Status Monitoring**: View web viewer status and port information
- **Configuration UI**: Manage IPTV settings through Jellyfin interface
- **API Integration**: Communicates with IPTV manager via REST API

### 11.2 Plugin Installation
1. **Build the Plugin** (requires .NET 8 SDK):
   ```bash
   cd /path/to/FfmpegMosaicPlugin
   dotnet publish -c Release -o ./publish
   ```

2. **Install on Synology**:
   ```bash
   # Create plugin directory
   sudo mkdir -p "/volume1/@appdata/jellyfin/config/plugins/FFmpeg Mosaic Plugin"
   
   # Copy plugin files
   sudo cp ./publish/* "/volume1/@appdata/jellyfin/config/plugins/FFmpeg Mosaic Plugin/"
   
   # Set permissions
   sudo chown -R jellyfin:jellyfin "/volume1/@appdata/jellyfin/config/plugins/FFmpeg Mosaic Plugin"
   ```

3. **Restart Jellyfin** and configure the plugin in Dashboard → Plugins

## Step 12: FFmpeg Mosaic Plugin (Advanced Alternative)

For users who prefer a server-side solution integrated with Jellyfin, the FFmpeg Mosaic Plugin provides an alternative approach. This plugin allows you to create a server-side video mosaic (e.g., a 2x2 grid of TV channels) with selectable audio tracks. The audio for each channel in the mosaic is preserved, allowing the user to switch between them during playback. Channel names are fetched from the Jellyfin API and used as audio track titles.

### 12.1 Prerequisites

- **.NET 8 SDK**: Required to build the plugin from source. You'll need to install this on a machine you can use for building, not necessarily on the NAS itself.
- **FFmpeg**: Must be installed on the same server as Jellyfin. The plugin will call the `ffmpeg` command directly.
- **Nginx**: A reverse proxy (like Nginx) is required to serve the generated HLS stream files.

### 12.2 Build Instructions

1.  **Download the source code** for the `FfmpegMosaicPlugin`.
2.  **Navigate to the project directory** on your build machine:
    ```bash
    cd /path/to/FfmpegMosaicPlugin
    ```
3.  **Build the plugin** in Release mode:
    ```bash
    dotnet publish -c Release -o ./publish
    ```
    This command will compile the plugin and place the necessary files into the `publish` directory.

### 12.3 Installation

1.  **Create the plugin directory** on your Jellyfin server. The directory name must be the plugin's name.
    ```bash
    # On your Synology NAS
    sudo mkdir -p "/volume1/@appdata/jellyfin/config/plugins/FFmpeg Mosaic Plugin"
    ```
2.  **Copy the built files** from your build machine's `publish` directory to the plugin directory you just created on the NAS. You should copy `FfmpegMosaicPlugin.dll` and any other dependency DLLs.
    ```bash
    # Example using scp from your build machine
    scp -r ./publish/* admin@YOUR_NAS_IP:"/volume1/@appdata/jellyfin/config/plugins/FFmpeg Mosaic Plugin/"
    ```
3.  **Set correct permissions** for the plugin files.
    ```bash
    # On your Synology NAS
    sudo chown -R jellyfin:jellyfin "/volume1/@appdata/jellyfin/config/plugins/FFmpeg Mosaic Plugin"
    ```
4.  **Restart Jellyfin** to load the new plugin. You can do this from the Synology Package Center.

### 12.4 Configuration

1.  **Configure the Plugin in Jellyfin**:
    - Go to **Jellyfin Dashboard** → **Plugins**.
    - Find **FFmpeg Mosaic Plugin** and click on its settings.
    - Set the **FFmpeg Executable Path** (e.g., `/usr/bin/ffmpeg`).
    - Set the **Mosaic Workspace Path** (e.g., `/var/lib/jellyfin/mosaics`). This directory must be writable by the `jellyfin` user.
    - Set the **Max Concurrent Mosaics**.
    - Click **Save**.

2.  **Configure Nginx**:
    - Add the provided `nginx.conf` snippet to your Jellyfin server block in your Nginx configuration. This allows Nginx to serve the HLS stream files generated by the plugin.
    - Make sure the `alias` path in the Nginx config matches the **Mosaic Workspace Path** you set in the plugin configuration.
    - Reload Nginx: `sudo nginx -s reload`

### 12.5 API Usage

- **Start a Mosaic**:
  - **Endpoint**: `POST /FfmpegMosaic/Start`
  - **Headers**: `X-Emby-Token: YOUR_API_KEY`
  - **Body** (JSON): `{"ChannelIds": ["channelId1", "channelId2", "channelId3", "channelId4"]}`
  - **Success Response**: `{"sessionId": "...", "url": ".../master.m3u8"}`

- **Stop a Mosaic**:
  - **Endpoint**: `POST /FfmpegMosaic/Stop/{sessionId}`
  - **Headers**: `X-Emby-Token: YOUR_API_KEY`

## Final Directory Structure

After successful deployment, your structure should look like:

```
/volume1/jellyfin/iptv-content/
├── IPV-Live/                    # Live TV .strm files
├── IPV-Movies/                  # Movie .strm files
│   └── Collections/             # Movie collections (Marvel, etc.)
├── IPV-Series/                  # TV series organized by season
│   └── [Series Name]/
│       └── Season 01/
├── IPV-Catchup/                 # Catchup content
├── IPV-Live_EPG.m3u            # Lightweight EPG playlist for Jellyfin
├── epg.xml                     # XMLTV EPG data
└── IPV_Merge_Report.txt        # Detailed content report

/volume1/docker/iptv-manager/
├── iptv_manager.py             # Main IPTV management script
├── manage_enhanced.py          # Enhanced monitoring & failover script
├── m3u_config.json            # IPTV configuration file
├── iptv_manager.log           # IPTV manager log file
├── monitoring.log             # Enhanced monitoring log file
└── m3u_last_update.json       # Update tracking
```

## Support

If you encounter issues:
1. Check the log file: `/volume1/docker/iptv-manager/iptv_manager.log`
2. Run a dry-run test to see what the script detects
3. Verify your IPTV provider credentials are correct
4. Ensure Jellyfin has proper permissions to read the content directories

The script is now ready for production use on your Synology NAS with Jellyfin!
