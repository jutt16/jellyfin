using System;
using System.Collections.Generic;
using System.Data.SQLite;
using System.IO;
using System.Threading.Tasks;
using MediaBrowser.Common.Configuration;
using Microsoft.Extensions.Logging;
using RecentChannelsPlugin.Models;

namespace RecentChannelsPlugin.Data
{
    public class RecentChannelsDatabase
    {
        private readonly ILogger<RecentChannelsDatabase> _logger;
        private readonly string _databasePath;

        public RecentChannelsDatabase(IApplicationPaths appPaths, ILogger<RecentChannelsDatabase> logger)
        {
            _logger = logger;
            _databasePath = Path.Combine(appPaths.DataPath, "recentchannels.db");
            InitializeDatabase();
        }

        private void InitializeDatabase()
        {
            try
            {
                using var connection = new SQLiteConnection($"Data Source={_databasePath}");
                connection.Open();

                var createTableCommand = @"
                    CREATE TABLE IF NOT EXISTS RecentChannels (
                        Id INTEGER PRIMARY KEY AUTOINCREMENT,
                        UserId TEXT NOT NULL,
                        ChannelId TEXT NOT NULL,
                        ChannelName TEXT NOT NULL,
                        ChannelNumber TEXT,
                        LastWatched DATETIME NOT NULL,
                        TotalWatchTimeSeconds INTEGER DEFAULT 0,
                        WatchCount INTEGER DEFAULT 1,
                        ChannelLogoUrl TEXT,
                        IsLive BOOLEAN DEFAULT 1,
                        CreatedAt DATETIME DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(UserId, ChannelId)
                    );

                    CREATE INDEX IF NOT EXISTS idx_user_lastwatched ON RecentChannels(UserId, LastWatched DESC);
                    CREATE INDEX IF NOT EXISTS idx_cleanup ON RecentChannels(LastWatched);
                ";

                using var command = new SQLiteCommand(createTableCommand, connection);
                command.ExecuteNonQuery();

                _logger.LogInformation("Recent Channels database initialized at {Path}", _databasePath);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to initialize Recent Channels database");
                throw;
            }
        }

        public async Task<bool> AddOrUpdateChannelAsync(RecentChannel channel)
        {
            try
            {
                using var connection = new SQLiteConnection($"Data Source={_databasePath}");
                await connection.OpenAsync();

                var upsertCommand = @"
                    INSERT INTO RecentChannels (UserId, ChannelId, ChannelName, ChannelNumber, LastWatched, TotalWatchTimeSeconds, WatchCount, ChannelLogoUrl, IsLive)
                    VALUES (@UserId, @ChannelId, @ChannelName, @ChannelNumber, @LastWatched, @TotalWatchTimeSeconds, @WatchCount, @ChannelLogoUrl, @IsLive)
                    ON CONFLICT(UserId, ChannelId) DO UPDATE SET
                        ChannelName = @ChannelName,
                        ChannelNumber = @ChannelNumber,
                        LastWatched = @LastWatched,
                        TotalWatchTimeSeconds = TotalWatchTimeSeconds + @TotalWatchTimeSeconds,
                        WatchCount = WatchCount + 1,
                        ChannelLogoUrl = @ChannelLogoUrl,
                        IsLive = @IsLive
                ";

                using var command = new SQLiteCommand(upsertCommand, connection);
                command.Parameters.AddWithValue("@UserId", channel.UserId);
                command.Parameters.AddWithValue("@ChannelId", channel.ChannelId);
                command.Parameters.AddWithValue("@ChannelName", channel.ChannelName);
                command.Parameters.AddWithValue("@ChannelNumber", channel.ChannelNumber ?? "");
                command.Parameters.AddWithValue("@LastWatched", channel.LastWatched);
                command.Parameters.AddWithValue("@TotalWatchTimeSeconds", channel.TotalWatchTimeSeconds);
                command.Parameters.AddWithValue("@WatchCount", channel.WatchCount);
                command.Parameters.AddWithValue("@ChannelLogoUrl", channel.ChannelLogoUrl ?? "");
                command.Parameters.AddWithValue("@IsLive", channel.IsLive);

                await command.ExecuteNonQueryAsync();
                return true;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to add/update recent channel for user {UserId}, channel {ChannelId}", 
                    channel.UserId, channel.ChannelId);
                return false;
            }
        }

        public async Task<List<RecentChannel>> GetRecentChannelsAsync(string userId, int limit = 20)
        {
            var channels = new List<RecentChannel>();

            try
            {
                using var connection = new SQLiteConnection($"Data Source={_databasePath}");
                await connection.OpenAsync();

                var selectCommand = @"
                    SELECT UserId, ChannelId, ChannelName, ChannelNumber, LastWatched, 
                           TotalWatchTimeSeconds, WatchCount, ChannelLogoUrl, IsLive
                    FROM RecentChannels 
                    WHERE UserId = @UserId 
                    ORDER BY LastWatched DESC 
                    LIMIT @Limit
                ";

                using var command = new SQLiteCommand(selectCommand, connection);
                command.Parameters.AddWithValue("@UserId", userId);
                command.Parameters.AddWithValue("@Limit", limit);

                using var reader = await command.ExecuteReaderAsync();
                while (await reader.ReadAsync())
                {
                    channels.Add(new RecentChannel
                    {
                        UserId = reader.GetString("UserId"),
                        ChannelId = reader.GetString("ChannelId"),
                        ChannelName = reader.GetString("ChannelName"),
                        ChannelNumber = reader.IsDBNull("ChannelNumber") ? null : reader.GetString("ChannelNumber"),
                        LastWatched = reader.GetDateTime("LastWatched"),
                        TotalWatchTimeSeconds = reader.GetInt32("TotalWatchTimeSeconds"),
                        WatchCount = reader.GetInt32("WatchCount"),
                        ChannelLogoUrl = reader.IsDBNull("ChannelLogoUrl") ? null : reader.GetString("ChannelLogoUrl"),
                        IsLive = reader.GetBoolean("IsLive")
                    });
                }
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to get recent channels for user {UserId}", userId);
            }

            return channels;
        }

        public async Task<bool> CleanupOldEntriesAsync(int retentionDays)
        {
            try
            {
                using var connection = new SQLiteConnection($"Data Source={_databasePath}");
                await connection.OpenAsync();

                var cutoffDate = DateTime.UtcNow.AddDays(-retentionDays);
                var deleteCommand = "DELETE FROM RecentChannels WHERE LastWatched < @CutoffDate";

                using var command = new SQLiteCommand(deleteCommand, connection);
                command.Parameters.AddWithValue("@CutoffDate", cutoffDate);

                var deletedRows = await command.ExecuteNonQueryAsync();
                _logger.LogInformation("Cleaned up {Count} old recent channel entries", deletedRows);

                return true;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to cleanup old recent channel entries");
                return false;
            }
        }

        public async Task<Dictionary<string, object>> GetStatisticsAsync()
        {
            var stats = new Dictionary<string, object>();

            try
            {
                using var connection = new SQLiteConnection($"Data Source={_databasePath}");
                await connection.OpenAsync();

                // Total channels tracked
                var totalCommand = "SELECT COUNT(DISTINCT ChannelId) FROM RecentChannels";
                using var totalCmd = new SQLiteCommand(totalCommand, connection);
                stats["TotalChannelsTracked"] = await totalCmd.ExecuteScalarAsync();

                // Total users
                var usersCommand = "SELECT COUNT(DISTINCT UserId) FROM RecentChannels";
                using var usersCmd = new SQLiteCommand(usersCommand, connection);
                stats["TotalUsers"] = await usersCmd.ExecuteScalarAsync();

                // Most watched channel
                var mostWatchedCommand = @"
                    SELECT ChannelName, SUM(WatchCount) as TotalWatches 
                    FROM RecentChannels 
                    GROUP BY ChannelId, ChannelName 
                    ORDER BY TotalWatches DESC 
                    LIMIT 1
                ";
                using var mostWatchedCmd = new SQLiteCommand(mostWatchedCommand, connection);
                using var reader = await mostWatchedCmd.ExecuteReaderAsync();
                if (await reader.ReadAsync())
                {
                    stats["MostWatchedChannel"] = reader.GetString("ChannelName");
                    stats["MostWatchedCount"] = reader.GetInt32("TotalWatches");
                }
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to get recent channels statistics");
            }

            return stats;
        }
    }
}
