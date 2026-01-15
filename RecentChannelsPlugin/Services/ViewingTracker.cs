using System;
using System.Threading.Tasks;
using MediaBrowser.Controller.Events;
using MediaBrowser.Controller.Events.Session;
using MediaBrowser.Controller.Library;
using MediaBrowser.Controller.Session;
using MediaBrowser.Model.Entities;
using Microsoft.Extensions.Logging;
using RecentChannelsPlugin.Models;

namespace RecentChannelsPlugin.Services
{
    public class ViewingTracker : IEventConsumer<PlaybackStartEventArgs>, 
                                  IEventConsumer<PlaybackStopEventArgs>,
                                  IEventConsumer<PlaybackProgressEventArgs>
    {
        private readonly RecentChannelsService _recentChannelsService;
        private readonly ILogger<ViewingTracker> _logger;
        private readonly ISessionManager _sessionManager;

        public ViewingTracker(
            RecentChannelsService recentChannelsService,
            ILogger<ViewingTracker> logger,
            ISessionManager sessionManager)
        {
            _recentChannelsService = recentChannelsService;
            _logger = logger;
            _sessionManager = sessionManager;
        }

        public async Task OnEvent(PlaybackStartEventArgs eventArgs)
        {
            try
            {
                if (!IsLiveTvChannel(eventArgs.Item))
                    return;

                var userId = eventArgs.Session.UserId.ToString();
                var channelId = eventArgs.Item.Id.ToString();
                var channelName = eventArgs.Item.Name;
                var channelNumber = GetChannelNumber(eventArgs.Item);
                var logoUrl = GetChannelLogoUrl(eventArgs.Item);

                var sessionId = await _recentChannelsService.StartViewingSessionAsync(
                    userId, channelId, channelName, channelNumber, logoUrl);

                // Store session ID in session data for later retrieval
                eventArgs.Session.AdditionalUsers.Add(new SessionUserInfo
                {
                    UserId = Guid.Parse(sessionId)
                });

                _logger.LogInformation("Started tracking Live TV viewing: User {UserId}, Channel {ChannelName}", 
                    userId, channelName);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to start tracking Live TV viewing");
            }
        }

        public async Task OnEvent(PlaybackStopEventArgs eventArgs)
        {
            try
            {
                if (!IsLiveTvChannel(eventArgs.Item))
                    return;

                var userId = eventArgs.Session.UserId.ToString();
                
                // Try to find and end the viewing session
                var sessionId = GetStoredSessionId(eventArgs.Session);
                if (!string.IsNullOrEmpty(sessionId))
                {
                    await _recentChannelsService.EndViewingSessionAsync(userId, sessionId);
                    _logger.LogInformation("Ended tracking Live TV viewing: User {UserId}, Session {SessionId}", 
                        userId, sessionId);
                }
                else
                {
                    // Fallback: track viewing directly if session ID not found
                    var channelId = eventArgs.Item.Id.ToString();
                    var channelName = eventArgs.Item.Name;
                    var channelNumber = GetChannelNumber(eventArgs.Item);
                    var logoUrl = GetChannelLogoUrl(eventArgs.Item);
                    var watchTime = eventArgs.PlaybackPositionTicks.HasValue 
                        ? (int)TimeSpan.FromTicks(eventArgs.PlaybackPositionTicks.Value).TotalSeconds 
                        : 0;

                    await _recentChannelsService.TrackViewingAsync(
                        userId, channelId, channelName, channelNumber, watchTime, logoUrl);
                }
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to stop tracking Live TV viewing");
            }
        }

        public async Task OnEvent(PlaybackProgressEventArgs eventArgs)
        {
            try
            {
                if (!IsLiveTvChannel(eventArgs.Item))
                    return;

                // Periodic updates could be handled here if needed
                // For now, we rely on start/stop events for tracking
                await Task.CompletedTask;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to process Live TV viewing progress");
            }
        }

        private static bool IsLiveTvChannel(BaseItem item)
        {
            return item != null && 
                   (item.SourceType == SourceType.LiveTV || 
                    item.GetType().Name.Contains("LiveTvChannel") ||
                    item.MediaType == MediaType.Video && item.IsFolder == false && 
                    item.LocationType == LocationType.Remote);
        }

        private static string? GetChannelNumber(BaseItem item)
        {
            // Try to extract channel number from various properties
            if (item.IndexNumber.HasValue)
                return item.IndexNumber.Value.ToString();

            if (item.ParentIndexNumber.HasValue)
                return item.ParentIndexNumber.Value.ToString();

            // Try to parse from name if it starts with a number
            var name = item.Name ?? "";
            var parts = name.Split(' ', StringSplitOptions.RemoveEmptyEntries);
            if (parts.Length > 0 && int.TryParse(parts[0], out var number))
                return number.ToString();

            return null;
        }

        private static string? GetChannelLogoUrl(BaseItem item)
        {
            try
            {
                if (item.HasImage(ImageType.Primary))
                {
                    return $"/Items/{item.Id}/Images/Primary";
                }

                if (item.HasImage(ImageType.Logo))
                {
                    return $"/Items/{item.Id}/Images/Logo";
                }

                if (item.HasImage(ImageType.Thumb))
                {
                    return $"/Items/{item.Id}/Images/Thumb";
                }
            }
            catch (Exception)
            {
                // Ignore image retrieval errors
            }

            return null;
        }

        private static string? GetStoredSessionId(SessionInfo session)
        {
            // This is a simplified approach - in a real implementation,
            // you might store session IDs in a more robust way
            try
            {
                if (session.AdditionalUsers?.Count > 0)
                {
                    return session.AdditionalUsers[^1].UserId.ToString();
                }
            }
            catch (Exception)
            {
                // Ignore retrieval errors
            }

            return null;
        }
    }
}
