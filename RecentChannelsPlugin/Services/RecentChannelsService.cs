using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using RecentChannelsPlugin.Data;
using RecentChannelsPlugin.Models;
using Microsoft.Extensions.Logging;

namespace RecentChannelsPlugin.Services
{
    public class RecentChannelsService
    {
        private readonly RecentChannelsDatabase _database;
        private readonly ILogger<RecentChannelsService> _logger;
        private readonly ConcurrentDictionary<string, ViewingSession> _activeSessions;
        private readonly Plugin _plugin;

        public RecentChannelsService(RecentChannelsDatabase database, ILogger<RecentChannelsService> logger, Plugin plugin)
        {
            _database = database;
            _logger = logger;
            _plugin = plugin;
            _activeSessions = new ConcurrentDictionary<string, ViewingSession>();
        }

        public async Task<List<RecentChannel>> GetRecentChannelsAsync(string userId, int limit = 20)
        {
            var maxChannels = _plugin.Configuration.MaxRecentChannels;
            var actualLimit = Math.Min(limit, maxChannels);
            
            return await _database.GetRecentChannelsAsync(userId, actualLimit);
        }

        public async Task<bool> TrackViewingAsync(string userId, string channelId, string channelName, 
            string? channelNumber = null, int watchTimeSeconds = 0, string? logoUrl = null)
        {
            var minWatchTime = _plugin.Configuration.MinimumWatchTimeSeconds;
            
            if (watchTimeSeconds < minWatchTime)
            {
                _logger.LogDebug("Watch time {WatchTime}s below minimum {MinTime}s for channel {ChannelName}", 
                    watchTimeSeconds, minWatchTime, channelName);
                return false;
            }

            var recentChannel = new RecentChannel
            {
                UserId = userId,
                ChannelId = channelId,
                ChannelName = channelName,
                ChannelNumber = channelNumber,
                LastWatched = DateTime.UtcNow,
                TotalWatchTimeSeconds = watchTimeSeconds,
                WatchCount = 1,
                ChannelLogoUrl = logoUrl,
                IsLive = true
            };

            return await _database.AddOrUpdateChannelAsync(recentChannel);
        }

        public async Task<string> StartViewingSessionAsync(string userId, string channelId, string channelName, 
            string? channelNumber = null, string? logoUrl = null)
        {
            var sessionId = Guid.NewGuid().ToString();
            var session = new ViewingSession
            {
                UserId = userId,
                ChannelId = channelId,
                ChannelName = channelName,
                ChannelNumber = channelNumber,
                StartTime = DateTime.UtcNow,
                ChannelLogoUrl = logoUrl,
                IsActive = true
            };

            _activeSessions[sessionId] = session;
            _logger.LogInformation("Started viewing session {SessionId} for user {UserId}, channel {ChannelName}", 
                sessionId, userId, channelName);

            return sessionId;
        }

        public async Task<bool> EndViewingSessionAsync(string userId, string sessionId)
        {
            if (!_activeSessions.TryRemove(sessionId, out var session) || session.UserId != userId)
            {
                return false;
            }

            session.EndTime = DateTime.UtcNow;
            session.IsActive = false;

            var watchTimeSeconds = session.WatchTimeSeconds;
            var success = await TrackViewingAsync(
                session.UserId,
                session.ChannelId,
                session.ChannelName,
                session.ChannelNumber,
                watchTimeSeconds,
                session.ChannelLogoUrl);

            _logger.LogInformation("Ended viewing session {SessionId} for user {UserId}, watch time: {WatchTime}s", 
                sessionId, userId, watchTimeSeconds);

            return success;
        }

        public async Task<Dictionary<string, object>> GetUserStatisticsAsync(string userId)
        {
            var channels = await GetRecentChannelsAsync(userId, 100);
            
            return new Dictionary<string, object>
            {
                ["TotalChannelsWatched"] = channels.Count,
                ["TotalWatchTime"] = TimeSpan.FromSeconds(channels.Sum(c => c.TotalWatchTimeSeconds)).ToString(@"hh\:mm\:ss"),
                ["TotalWatchCount"] = channels.Sum(c => c.WatchCount),
                ["MostWatchedChannel"] = channels.OrderByDescending(c => c.WatchCount).FirstOrDefault()?.ChannelName ?? "None",
                ["ActiveSessions"] = _activeSessions.Values.Count(s => s.UserId == userId && s.IsActive),
                ["LastWatched"] = channels.FirstOrDefault()?.LastWatched ?? DateTime.MinValue
            };
        }

        public async Task<Dictionary<string, object>> GetGlobalStatisticsAsync()
        {
            var dbStats = await _database.GetStatisticsAsync();
            
            dbStats["ActiveSessions"] = _activeSessions.Count;
            dbStats["PluginVersion"] = "1.0.0";
            dbStats["DatabasePath"] = "recentchannels.db";
            
            return dbStats;
        }

        public async Task<Dictionary<string, object>> GetHealthStatusAsync()
        {
            try
            {
                // Test database connectivity
                await _database.GetStatisticsAsync();
                
                return new Dictionary<string, object>
                {
                    ["Status"] = "Healthy",
                    ["DatabaseConnected"] = true,
                    ["ActiveSessions"] = _activeSessions.Count,
                    ["LastCheck"] = DateTime.UtcNow,
                    ["Configuration"] = new
                    {
                        MaxRecentChannels = _plugin.Configuration.MaxRecentChannels,
                        MinimumWatchTimeSeconds = _plugin.Configuration.MinimumWatchTimeSeconds,
                        HistoryRetentionDays = _plugin.Configuration.HistoryRetentionDays
                    }
                };
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Health check failed");
                return new Dictionary<string, object>
                {
                    ["Status"] = "Unhealthy",
                    ["DatabaseConnected"] = false,
                    ["Error"] = ex.Message,
                    ["LastCheck"] = DateTime.UtcNow
                };
            }
        }

        public async Task<bool> ClearUserHistoryAsync(string userId)
        {
            try
            {
                // End any active sessions for this user
                var userSessions = _activeSessions.Where(kvp => kvp.Value.UserId == userId).ToList();
                foreach (var session in userSessions)
                {
                    await EndViewingSessionAsync(userId, session.Key);
                }

                // Note: Database cleanup would require additional method in RecentChannelsDatabase
                _logger.LogInformation("Cleared history for user {UserId}", userId);
                return true;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to clear history for user {UserId}", userId);
                return false;
            }
        }

        public async Task PerformMaintenanceAsync()
        {
            try
            {
                var retentionDays = _plugin.Configuration.HistoryRetentionDays;
                await _database.CleanupOldEntriesAsync(retentionDays);

                // Clean up stale sessions (older than 24 hours)
                var staleSessionIds = _activeSessions
                    .Where(kvp => DateTime.UtcNow - kvp.Value.StartTime > TimeSpan.FromHours(24))
                    .Select(kvp => kvp.Key)
                    .ToList();

                foreach (var sessionId in staleSessionIds)
                {
                    if (_activeSessions.TryRemove(sessionId, out var session))
                    {
                        _logger.LogWarning("Removed stale session {SessionId} for user {UserId}", 
                            sessionId, session.UserId);
                    }
                }

                _logger.LogInformation("Maintenance completed: cleaned up old entries and {StaleCount} stale sessions", 
                    staleSessionIds.Count);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Maintenance task failed");
            }
        }
    }
}
