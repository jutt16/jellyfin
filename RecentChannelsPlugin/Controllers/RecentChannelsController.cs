using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using RecentChannelsPlugin.Models;
using RecentChannelsPlugin.Services;
using MediaBrowser.Controller.Session;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;

namespace RecentChannelsPlugin.Controllers
{
    [ApiController]
    [Route("Plugins/RecentChannels")]
    [Authorize(Policy = "DefaultAuthorization")]
    public class RecentChannelsController : ControllerBase
    {
        private readonly RecentChannelsService _recentChannelsService;
        private readonly ISessionManager _sessionManager;
        private readonly ILogger<RecentChannelsController> _logger;

        public RecentChannelsController(
            RecentChannelsService recentChannelsService,
            ISessionManager sessionManager,
            ILogger<RecentChannelsController> logger)
        {
            _recentChannelsService = recentChannelsService;
            _sessionManager = sessionManager;
            _logger = logger;
        }

        [HttpGet("{userId}/RecentChannels")]
        public async Task<ActionResult<List<RecentChannelDto>>> GetRecentChannels(
            [FromRoute] string userId,
            [FromQuery] int limit = 20)
        {
            try
            {
                var channels = await _recentChannelsService.GetRecentChannelsAsync(userId, limit);
                var dtos = channels.Select(c => new RecentChannelDto
                {
                    UserId = c.UserId,
                    ChannelId = c.ChannelId,
                    ChannelName = c.ChannelName,
                    ChannelNumber = c.ChannelNumber,
                    LastWatched = c.LastWatched,
                    TotalWatchTime = c.TotalWatchTimeFormatted,
                    WatchCount = c.WatchCount,
                    ChannelLogoUrl = c.ChannelLogoUrl,
                    IsLive = c.IsLive
                }).ToList();

                return Ok(dtos);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to get recent channels for user {UserId}", userId);
                return StatusCode(500, "Internal server error");
            }
        }

        [HttpPost("{userId}/TrackViewing")]
        public async Task<ActionResult> TrackViewing(
            [FromRoute] string userId,
            [FromBody] TrackViewingRequest request)
        {
            try
            {
                if (string.IsNullOrEmpty(request.ChannelId) || string.IsNullOrEmpty(request.ChannelName))
                {
                    return BadRequest("ChannelId and ChannelName are required");
                }

                await _recentChannelsService.TrackViewingAsync(
                    userId,
                    request.ChannelId,
                    request.ChannelName,
                    request.ChannelNumber,
                    request.WatchTimeSeconds,
                    request.ChannelLogoUrl);

                return Ok(new { message = "Viewing tracked successfully" });
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to track viewing for user {UserId}, channel {ChannelId}", 
                    userId, request.ChannelId);
                return StatusCode(500, "Internal server error");
            }
        }

        [HttpPost("{userId}/StartSession")]
        public async Task<ActionResult> StartViewingSession(
            [FromRoute] string userId,
            [FromBody] StartSessionRequest request)
        {
            try
            {
                var sessionId = await _recentChannelsService.StartViewingSessionAsync(
                    userId,
                    request.ChannelId,
                    request.ChannelName,
                    request.ChannelNumber,
                    request.ChannelLogoUrl);

                return Ok(new { sessionId });
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to start viewing session for user {UserId}, channel {ChannelId}", 
                    userId, request.ChannelId);
                return StatusCode(500, "Internal server error");
            }
        }

        [HttpPost("{userId}/EndSession/{sessionId}")]
        public async Task<ActionResult> EndViewingSession(
            [FromRoute] string userId,
            [FromRoute] string sessionId)
        {
            try
            {
                var success = await _recentChannelsService.EndViewingSessionAsync(userId, sessionId);
                if (success)
                {
                    return Ok(new { message = "Session ended successfully" });
                }
                return NotFound(new { message = "Session not found" });
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to end viewing session {SessionId} for user {UserId}", 
                    sessionId, userId);
                return StatusCode(500, "Internal server error");
            }
        }

        [HttpGet("{userId}/Statistics")]
        public async Task<ActionResult> GetUserStatistics([FromRoute] string userId)
        {
            try
            {
                var stats = await _recentChannelsService.GetUserStatisticsAsync(userId);
                return Ok(stats);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to get statistics for user {UserId}", userId);
                return StatusCode(500, "Internal server error");
            }
        }

        [HttpGet("Health")]
        public async Task<ActionResult> GetHealth()
        {
            try
            {
                var health = await _recentChannelsService.GetHealthStatusAsync();
                return Ok(health);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to get health status");
                return StatusCode(500, "Internal server error");
            }
        }

        [HttpGet("Statistics")]
        [Authorize(Policy = "RequiresElevation")]
        public async Task<ActionResult> GetGlobalStatistics()
        {
            try
            {
                var stats = await _recentChannelsService.GetGlobalStatisticsAsync();
                return Ok(stats);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to get global statistics");
                return StatusCode(500, "Internal server error");
            }
        }

        [HttpDelete("{userId}/Clear")]
        public async Task<ActionResult> ClearUserHistory([FromRoute] string userId)
        {
            try
            {
                var success = await _recentChannelsService.ClearUserHistoryAsync(userId);
                if (success)
                {
                    return Ok(new { message = "History cleared successfully" });
                }
                return StatusCode(500, "Failed to clear history");
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to clear history for user {UserId}", userId);
                return StatusCode(500, "Internal server error");
            }
        }
    }

    public class TrackViewingRequest
    {
        public string ChannelId { get; set; } = string.Empty;
        public string ChannelName { get; set; } = string.Empty;
        public string? ChannelNumber { get; set; }
        public int WatchTimeSeconds { get; set; }
        public string? ChannelLogoUrl { get; set; }
    }

    public class StartSessionRequest
    {
        public string ChannelId { get; set; } = string.Empty;
        public string ChannelName { get; set; } = string.Empty;
        public string? ChannelNumber { get; set; }
        public string? ChannelLogoUrl { get; set; }
    }
}
