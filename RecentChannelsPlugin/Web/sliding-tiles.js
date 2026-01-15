/**
 * Recent Channels Sliding Tiles Interface
 * TiviMate-style sliding tiles for Jellyfin Live TV
 */

class RecentChannelsTiles {
    constructor(options = {}) {
        this.userId = options.userId || '';
        this.apiBaseUrl = options.apiBaseUrl || '/Plugins/RecentChannels';
        this.autoHideDelay = options.autoHideDelay || 5000;
        this.maxTiles = options.maxTiles || 10;
        this.isVisible = false;
        this.hideTimeout = null;
        this.currentChannelId = null;
        
        this.init();
    }

    init() {
        this.createTilesContainer();
        this.bindEvents();
        this.loadRecentChannels();
    }

    createTilesContainer() {
        // Remove existing container if present
        const existing = document.getElementById('recent-channels-tiles');
        if (existing) existing.remove();

        // Create main container
        this.container = document.createElement('div');
        this.container.id = 'recent-channels-tiles';
        this.container.className = 'recent-tiles-container hidden';
        
        // Create tiles wrapper
        this.tilesWrapper = document.createElement('div');
        this.tilesWrapper.className = 'tiles-wrapper';
        
        this.container.appendChild(this.tilesWrapper);
        document.body.appendChild(this.container);

        // Add CSS styles
        this.addStyles();
    }

    addStyles() {
        const styleId = 'recent-channels-styles';
        if (document.getElementById(styleId)) return;

        const style = document.createElement('style');
        style.id = styleId;
        style.textContent = `
            .recent-tiles-container {
                position: fixed;
                bottom: 0;
                left: 0;
                right: 0;
                z-index: 10000;
                background: linear-gradient(transparent, rgba(0,0,0,0.8));
                padding: 20px;
                transform: translateY(100%);
                transition: transform 0.3s ease-in-out;
                pointer-events: none;
            }

            .recent-tiles-container.visible {
                transform: translateY(0);
                pointer-events: auto;
            }

            .recent-tiles-container.hidden {
                transform: translateY(100%);
            }

            .tiles-wrapper {
                display: flex;
                gap: 15px;
                overflow-x: auto;
                padding: 10px 0;
                scrollbar-width: none;
                -ms-overflow-style: none;
            }

            .tiles-wrapper::-webkit-scrollbar {
                display: none;
            }

            .channel-tile {
                min-width: 120px;
                max-width: 150px;
                background: rgba(255,255,255,0.1);
                border-radius: 8px;
                padding: 12px;
                cursor: pointer;
                transition: all 0.2s ease;
                border: 2px solid transparent;
                backdrop-filter: blur(10px);
            }

            .channel-tile:hover {
                background: rgba(255,255,255,0.2);
                transform: translateY(-2px);
            }

            .channel-tile.current {
                border-color: #00a4dc;
                background: linear-gradient(135deg, rgba(0,164,220,0.3), rgba(0,164,220,0.1));
            }

            .tile-logo {
                width: 60px;
                height: 40px;
                object-fit: contain;
                margin: 0 auto 8px;
                display: block;
                border-radius: 4px;
                background: rgba(255,255,255,0.1);
            }

            .tile-name {
                color: white;
                font-size: 12px;
                font-weight: 500;
                text-align: center;
                margin-bottom: 4px;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }

            .tile-info {
                display: flex;
                justify-content: space-between;
                align-items: center;
                font-size: 10px;
                color: rgba(255,255,255,0.7);
            }

            .tile-number {
                background: rgba(0,164,220,0.8);
                color: white;
                padding: 2px 6px;
                border-radius: 10px;
                font-weight: bold;
            }

            .tile-time {
                font-size: 9px;
            }

            .live-indicator {
                position: absolute;
                top: 8px;
                right: 8px;
                width: 8px;
                height: 8px;
                background: #ff4444;
                border-radius: 50%;
                animation: pulse 2s infinite;
            }

            @keyframes pulse {
                0% { opacity: 1; }
                50% { opacity: 0.5; }
                100% { opacity: 1; }
            }

            .tiles-loading {
                color: white;
                text-align: center;
                padding: 20px;
                font-size: 14px;
            }

            .tiles-error {
                color: #ff6b6b;
                text-align: center;
                padding: 20px;
                font-size: 14px;
            }

            /* Mobile optimizations */
            @media (max-width: 768px) {
                .channel-tile {
                    min-width: 100px;
                    max-width: 120px;
                    padding: 10px;
                }
                
                .tile-logo {
                    width: 50px;
                    height: 35px;
                }
                
                .tile-name {
                    font-size: 11px;
                }
            }
        `;
        
        document.head.appendChild(style);
    }

    bindEvents() {
        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            if (e.key === 'r' || e.key === 'R') {
                if (e.ctrlKey || e.metaKey) return; // Don't interfere with browser refresh
                this.toggle();
            } else if (e.key === 'Escape' && this.isVisible) {
                this.hide();
            }
        });

        // Touch/swipe gestures for mobile
        let touchStartY = 0;
        let touchStartX = 0;
        
        document.addEventListener('touchstart', (e) => {
            touchStartY = e.touches[0].clientY;
            touchStartX = e.touches[0].clientX;
        });

        document.addEventListener('touchend', (e) => {
            const touchEndY = e.changedTouches[0].clientY;
            const touchEndX = e.changedTouches[0].clientX;
            const deltaY = touchStartY - touchEndY;
            const deltaX = Math.abs(touchStartX - touchEndX);
            
            // Swipe up from bottom to show tiles
            if (deltaY > 50 && deltaX < 100 && touchStartY > window.innerHeight - 100) {
                this.show();
            }
            // Swipe down to hide tiles
            else if (deltaY < -30 && this.isVisible && deltaX < 100) {
                this.hide();
            }
        });

        // Click outside to hide
        document.addEventListener('click', (e) => {
            if (this.isVisible && !this.container.contains(e.target)) {
                this.hide();
            }
        });

        // Auto-hide on mouse leave
        this.container.addEventListener('mouseleave', () => {
            if (this.isVisible) {
                this.scheduleAutoHide();
            }
        });

        this.container.addEventListener('mouseenter', () => {
            this.cancelAutoHide();
        });
    }

    async loadRecentChannels() {
        if (!this.userId) {
            console.warn('Recent Channels: No user ID provided');
            return;
        }

        try {
            this.showLoading();
            
            const response = await fetch(`${this.apiBaseUrl}/${this.userId}/RecentChannels?limit=${this.maxTiles}`, {
                headers: {
                    'X-Emby-Token': this.getApiToken()
                }
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const channels = await response.json();
            this.renderTiles(channels);
            
        } catch (error) {
            console.error('Failed to load recent channels:', error);
            this.showError('Failed to load recent channels');
        }
    }

    renderTiles(channels) {
        this.tilesWrapper.innerHTML = '';

        if (!channels || channels.length === 0) {
            this.tilesWrapper.innerHTML = '<div class="tiles-loading">No recent channels found</div>';
            return;
        }

        channels.forEach((channel, index) => {
            const tile = this.createTile(channel, index);
            this.tilesWrapper.appendChild(tile);
        });
    }

    createTile(channel, index) {
        const tile = document.createElement('div');
        tile.className = 'channel-tile';
        tile.dataset.channelId = channel.ChannelId;
        
        if (channel.ChannelId === this.currentChannelId) {
            tile.classList.add('current');
        }

        const logo = document.createElement('img');
        logo.className = 'tile-logo';
        logo.src = channel.ChannelLogoUrl || '/web/assets/img/icon-transparent.png';
        logo.alt = channel.ChannelName;
        logo.onerror = () => {
            logo.src = '/web/assets/img/icon-transparent.png';
        };

        const name = document.createElement('div');
        name.className = 'tile-name';
        name.textContent = channel.ChannelName;
        name.title = channel.ChannelName;

        const info = document.createElement('div');
        info.className = 'tile-info';

        const number = document.createElement('span');
        number.className = 'tile-number';
        number.textContent = channel.ChannelNumber || (index + 1);

        const time = document.createElement('span');
        time.className = 'tile-time';
        time.textContent = channel.TotalWatchTime || '0:00';

        info.appendChild(number);
        info.appendChild(time);

        if (channel.IsLive) {
            const liveIndicator = document.createElement('div');
            liveIndicator.className = 'live-indicator';
            tile.appendChild(liveIndicator);
        }

        tile.appendChild(logo);
        tile.appendChild(name);
        tile.appendChild(info);

        // Click handler for channel switching
        tile.addEventListener('click', () => {
            this.switchToChannel(channel);
        });

        return tile;
    }

    switchToChannel(channel) {
        // Emit custom event for Jellyfin to handle channel switching
        const event = new CustomEvent('recentChannelSelected', {
            detail: {
                channelId: channel.ChannelId,
                channelName: channel.ChannelName,
                channelNumber: channel.ChannelNumber
            }
        });
        
        document.dispatchEvent(event);
        
        // Update current channel
        this.currentChannelId = channel.ChannelId;
        this.updateCurrentTile();
        
        // Hide tiles after selection
        setTimeout(() => this.hide(), 300);
    }

    updateCurrentTile() {
        const tiles = this.tilesWrapper.querySelectorAll('.channel-tile');
        tiles.forEach(tile => {
            tile.classList.toggle('current', tile.dataset.channelId === this.currentChannelId);
        });
    }

    show() {
        this.container.classList.remove('hidden');
        this.container.classList.add('visible');
        this.isVisible = true;
        this.scheduleAutoHide();
        
        // Refresh data when showing
        this.loadRecentChannels();
    }

    hide() {
        this.container.classList.remove('visible');
        this.container.classList.add('hidden');
        this.isVisible = false;
        this.cancelAutoHide();
    }

    toggle() {
        if (this.isVisible) {
            this.hide();
        } else {
            this.show();
        }
    }

    scheduleAutoHide() {
        this.cancelAutoHide();
        this.hideTimeout = setTimeout(() => {
            this.hide();
        }, this.autoHideDelay);
    }

    cancelAutoHide() {
        if (this.hideTimeout) {
            clearTimeout(this.hideTimeout);
            this.hideTimeout = null;
        }
    }

    showLoading() {
        this.tilesWrapper.innerHTML = '<div class="tiles-loading">Loading recent channels...</div>';
    }

    showError(message) {
        this.tilesWrapper.innerHTML = `<div class="tiles-error">${message}</div>`;
    }

    setCurrentChannel(channelId) {
        this.currentChannelId = channelId;
        this.updateCurrentTile();
    }

    setUserId(userId) {
        this.userId = userId;
        this.loadRecentChannels();
    }

    getApiToken() {
        // Try to get API token from various Jellyfin client methods
        if (typeof ApiClient !== 'undefined' && ApiClient.accessToken) {
            return ApiClient.accessToken();
        }
        
        // Fallback: try to get from localStorage
        const authData = localStorage.getItem('jellyfin_credentials');
        if (authData) {
            try {
                const parsed = JSON.parse(authData);
                return parsed.AccessToken;
            } catch (e) {
                console.warn('Failed to parse stored auth data');
            }
        }
        
        return '';
    }

    destroy() {
        this.cancelAutoHide();
        if (this.container) {
            this.container.remove();
        }
        
        const style = document.getElementById('recent-channels-styles');
        if (style) {
            style.remove();
        }
    }
}

// Auto-initialize when Jellyfin is ready
document.addEventListener('DOMContentLoaded', () => {
    // Wait for Jellyfin to be ready
    const initWhenReady = () => {
        if (typeof ApiClient !== 'undefined' && ApiClient.getCurrentUserId) {
            const userId = ApiClient.getCurrentUserId();
            if (userId) {
                window.recentChannelsTiles = new RecentChannelsTiles({
                    userId: userId,
                    autoHideDelay: 5000,
                    maxTiles: 10
                });
                
                console.log('Recent Channels Tiles initialized for user:', userId);
                return;
            }
        }
        
        // Retry after 500ms if not ready
        setTimeout(initWhenReady, 500);
    };
    
    initWhenReady();
});

// Export for manual initialization
if (typeof module !== 'undefined' && module.exports) {
    module.exports = RecentChannelsTiles;
}
