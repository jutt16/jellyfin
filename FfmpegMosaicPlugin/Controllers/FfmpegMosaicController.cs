using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using FfmpegMosaicPlugin.Models;
using FfmpegMosaicPlugin.Services;
using MediaBrowser.Controller.Session;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace FfmpegMosaicPlugin.Controllers
{
    [ApiController]
    [Route("FfmpegMosaic")]
    [Authorize(Policy = "DefaultAuthorization")]
    public class FfmpegMosaicController : ControllerBase
    {
        private readonly FfmpegMosaicService _mosaicService;
        private readonly ISessionManager _sessionManager;

        public FfmpegMosaicController(FfmpegMosaicService mosaicService, ISessionManager sessionManager)
        {
            _mosaicService = mosaicService;
            _sessionManager = sessionManager;
        }

        [HttpPost("Start")]
        public async Task<ActionResult> Start([FromBody] StartRequest request)
        {
            if (request?.ChannelIds == null || request.ChannelIds.Count == 0)
            {
                return BadRequest("At least one channel ID is required");
            }

            var token = Request.Headers["X-Emby-Token"].FirstOrDefault();
            if (string.IsNullOrEmpty(token))
            {
                return Unauthorized("API token is required");
            }

            try
            {
                var sessionInfo = await _sessionManager.GetSessionByAuthenticationTokenAsync(token, Request.HttpContext.Connection.RemoteIpAddress?.ToString(), "mosaic-plugin");
                if (sessionInfo == null) return Unauthorized();

                var session = new MosaicSession
                {
                    OwnerUserId = sessionInfo.UserId.ToString(),
                    ChannelIds = request.ChannelIds
                };

                var result = await _mosaicService.StartAsync(session, token);
                var baseUrl = $"{Request.Scheme}://{Request.Host}";
                return Ok(new { sessionId = result.Id, url = baseUrl + result.OutputRelativePath });
            }
            catch (ArgumentException ex)
            {
                return BadRequest(ex.Message);
            }
            catch (InvalidOperationException ex)
            {
                return StatusCode(500, ex.Message);
            }
        }

        [HttpPost("Stop/{id}")]
        public IActionResult Stop(string id)
        {
            if (string.IsNullOrEmpty(id))
            {
                return BadRequest("Session ID is required");
            }

            if (_mosaicService.Stop(id))
            {
                return Ok(new { message = "Session stopped successfully" });
            }
            return NotFound(new { message = "Session not found" });
        }

        public class StartRequest
        {
            public List<string> ChannelIds { get; set; } = new List<string>();
        }
    }
}
