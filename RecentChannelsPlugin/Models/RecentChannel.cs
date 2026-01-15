using System;

namespace RecentChannelsPlugin.Models
{
    public class RecentChannel
    {
        public string UserId { get; set; } = string.Empty;
        public string ChannelId { get; set; } = string.Empty;
        public string ChannelName { get; set; } = string.Empty;
        public string? ChannelNumber { get; set; }
        public DateTime LastWatched { get; set; }
        public int TotalWatchTimeSeconds { get; set; }
        public int WatchCount { get; set; }
        public string? ChannelLogoUrl { get; set; }
        public bool IsLive { get; set; } = true;

        public string TotalWatchTimeFormatted => TimeSpan.FromSeconds(TotalWatchTimeSeconds).ToString(@"hh\:mm\:ss");
    }

    public class RecentChannelDto
    {
        public string UserId { get; set; } = string.Empty;
        public string ChannelId { get; set; } = string.Empty;
        public string ChannelName { get; set; } = string.Empty;
        public string? ChannelNumber { get; set; }
        public DateTime LastWatched { get; set; }
        public string TotalWatchTime { get; set; } = string.Empty;
        public int WatchCount { get; set; }
        public string? ChannelLogoUrl { get; set; }
        public bool IsLive { get; set; }
    }

    public class ViewingSession
    {
        public string UserId { get; set; } = string.Empty;
        public string ChannelId { get; set; } = string.Empty;
        public string ChannelName { get; set; } = string.Empty;
        public string? ChannelNumber { get; set; }
        public DateTime StartTime { get; set; }
        public DateTime? EndTime { get; set; }
        public string? ChannelLogoUrl { get; set; }
        public bool IsActive { get; set; } = true;

        public int WatchTimeSeconds => EndTime.HasValue 
            ? (int)(EndTime.Value - StartTime).TotalSeconds 
            : (int)(DateTime.UtcNow - StartTime).TotalSeconds;
    }
}
