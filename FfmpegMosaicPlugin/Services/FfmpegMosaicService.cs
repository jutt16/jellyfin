using System;
using System.Collections.Concurrent;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using FfmpegMosaicPlugin.Models;
using MediaBrowser.Common.Configuration;
using MediaBrowser.Controller.LiveTv;
using MediaBrowser.Controller.Session;

namespace FfmpegMosaicPlugin.Services
{
    public class FfmpegMosaicService : IDisposable
    {
        private readonly string _workspaceRoot;
        private readonly string _ffmpegPath;
        private readonly ConcurrentDictionary<string, MosaicSession> _sessions = new();
        private readonly SemaphoreSlim _concurrencySemaphore;
        private readonly ILiveTvManager _liveTvManager;
        private readonly ISessionManager _sessionManager;

        public FfmpegMosaicService(IApplicationPaths appPaths, ILiveTvManager liveTvManager, ISessionManager sessionManager)
        {
            var config = Plugin.Instance?.Configuration ?? new PluginConfiguration();
            _workspaceRoot = !string.IsNullOrEmpty(config.WorkspacePath) ? config.WorkspacePath : Path.Combine(appPaths.DataPath, "ffmpeg-mosaic");
            _ffmpegPath = !string.IsNullOrEmpty(config.FfmpegPath) ? config.FfmpegPath : "ffmpeg";
            _concurrencySemaphore = new SemaphoreSlim(Math.Max(1, config.MaxConcurrentMosaics));
            _liveTvManager = liveTvManager;
            _sessionManager = sessionManager;
            
            try
            {
                Directory.CreateDirectory(_workspaceRoot);
            }
            catch (Exception ex)
            {
                throw new InvalidOperationException($"Failed to create workspace directory: {_workspaceRoot}", ex);
            }
        }

        public async Task<MosaicSession> StartAsync(MosaicSession session, string apiKey)
        {
            if (session == null)
                throw new ArgumentNullException(nameof(session));
            
            if (session.ChannelIds == null || !session.ChannelIds.Any())
                throw new ArgumentException("At least one channel ID is required", nameof(session));

            await _concurrencySemaphore.WaitAsync();

            var sessionDir = Path.Combine(_workspaceRoot, session.Id);
            
            try
            {
                Directory.CreateDirectory(sessionDir);
            }
            catch (Exception ex)
            {
                _concurrencySemaphore.Release();
                throw new InvalidOperationException($"Failed to create session directory: {sessionDir}", ex);
            }

            try
            {
                // Validate and get Live TV stream URLs and channel names
                var validChannels = new List<string>();
                
                foreach (var channelId in session.ChannelIds)
                {
                    try
                    {
                        if (string.IsNullOrWhiteSpace(channelId))
                        {
                            System.Diagnostics.Debug.WriteLine($"Skipping empty channel ID");
                            continue;
                        }

                        var channel = await _liveTvManager.GetChannelAsync(channelId, CancellationToken.None);
                        if (channel == null)
                        {
                            System.Diagnostics.Debug.WriteLine($"Channel {channelId} not found, skipping");
                            continue;
                        }
                        
                        var mediaSource = await _liveTvManager.GetChannelStreamAsync(channelId, string.Empty, CancellationToken.None);
                        if (mediaSource == null || string.IsNullOrWhiteSpace(mediaSource.Path))
                        {
                            System.Diagnostics.Debug.WriteLine($"No media source for channel {channelId}, skipping");
                            continue;
                        }

                        session.InputUrls[channelId] = mediaSource.Path;
                        session.ChannelNames[channelId] = channel.Name ?? $"Channel {channelId}";
                        validChannels.Add(channelId);
                    }
                    catch (Exception ex)
                    {
                        System.Diagnostics.Debug.WriteLine($"Error processing channel {channelId}: {ex.Message}");
                        // Continue with other channels
                    }
                }

                if (!validChannels.Any())
                {
                    throw new ArgumentException("No valid channels found from the provided channel IDs");
                }

                // Update session with only valid channels
                session.ChannelIds = validChannels;

                var ffmpegArgs = BuildFfmpegCommand(session, sessionDir, apiKey);
                var process = StartFfmpegProcess(ffmpegArgs, session.Id);

                if (process == null || process.HasExited)
                {
                    throw new InvalidOperationException("FFmpeg process failed to start or exited immediately");
                }

                session.FfmpegProcess = process;
                session.Cts = new CancellationTokenSource();
                session.OutputRelativePath = $"/mosaics/{session.Id}/master.m3u8";
                _sessions[session.Id] = session;

                _ = MonitorSessionLifetime(session.Id, session.Cts.Token);

                return session;
            }
            catch (Exception ex)
            {
                // Cleanup on failure
                try 
                { 
                    if (Directory.Exists(sessionDir))
                        Directory.Delete(sessionDir, true); 
                } 
                catch (Exception cleanupEx)
                {
                    System.Diagnostics.Debug.WriteLine($"Failed to cleanup session directory: {cleanupEx.Message}");
                }
                
                _concurrencySemaphore.Release();
                throw new InvalidOperationException($"Failed to start mosaic session: {ex.Message}", ex);
            }
        }

        private string BuildFfmpegCommand(MosaicSession session, string sessionDir, string apiKey)
        {
            var sb = new StringBuilder();
            var headerFile = CreateHeaderFile(sessionDir, apiKey);

            // Inputs
            var headerContent = File.Exists(headerFile) ? File.ReadAllText(headerFile).Trim() : "";
            foreach (var url in session.InputUrls.Values)
            {
                if (!string.IsNullOrEmpty(headerContent))
                {
                    sb.Append($"-headers \"{EscapeArg(headerContent)}\" ");
                }
                sb.Append($"-i \"{EscapeArg(url)}\" ");
            }

            // Filter Complex
            sb.Append("-filter_complex \"");
            var videoMaps = new StringBuilder();
            for (int i = 0; i < session.InputUrls.Count; i++)
            {
                sb.Append($"[{i}:v]setpts=PTS-STARTPTS,scale={session.TileW}x{session.TileH},setsar=1[v{i}];");
            }
            
            if (session.InputUrls.Count == 4)
            {
                sb.Append("[v0][v1][v2][v3]xstack=inputs=4:layout=0_0|w0_0|0_h0|w0_h0[outv]");
            }
            else if (session.InputUrls.Count > 1) // Basic hstack for 2-3 inputs
            {
                 for (int i = 0; i < session.InputUrls.Count; i++) videoMaps.Append($"[v{i}]");
                 sb.Append($"{videoMaps}hstack=inputs={session.InputUrls.Count}[outv]");
            }
            else // Single input
            {
                sb.Append("[v0]copy[outv]");
            }
            sb.Append("\" ");

            // Video and Audio Mapping
            sb.Append("-map \"[outv]\" ");
            for (int i = 0; i < session.InputUrls.Count; i++)
            {
                if (i < session.ChannelIds.Count)
                {
                    var channelId = session.ChannelIds[i];
                    var channelName = session.ChannelNames.ContainsKey(channelId) ? session.ChannelNames[channelId] : $"Channel {i + 1}";
                    sb.Append($"-map {i}:a -metadata:s:a:{i} title=\"{EscapeArg(channelName)}\" ");
                }
                else
                {
                    sb.Append($"-map {i}:a -metadata:s:a:{i} title=\"Channel {i + 1}\" ");
                }
            }

            // Output settings
            var masterPlaylist = Path.Combine(sessionDir, "master.m3u8");
            sb.Append($"-c:v libx264 -preset veryfast -crf 23 -c:a aac -b:a 128k -f hls -hls_time 4 -hls_list_size 6 -hls_flags delete_segments \"{EscapeArg(masterPlaylist)}\"");

            return sb.ToString();
        }

        private Process StartFfmpegProcess(string args, string sessionId)
        {
            var psi = new ProcessStartInfo
            {
                FileName = _ffmpegPath,
                Arguments = args,
                UseShellExecute = false,
                RedirectStandardError = true,
                CreateNoWindow = true
            };

            var proc = new Process { StartInfo = psi, EnableRaisingEvents = true };
            proc.ErrorDataReceived += (s, e) => { if (e.Data != null) System.Diagnostics.Debug.WriteLine($"[ffmpeg:{sessionId}] {e.Data}"); };
            proc.Exited += (s, e) => Stop(sessionId);

            proc.Start();
            proc.BeginErrorReadLine();
            return proc;
        }

        public bool Stop(string id)
        {
            if (!_sessions.TryRemove(id, out var session)) return false;

            try
            {
                session.Cts?.Cancel();
                if (session.FfmpegProcess != null && !session.FfmpegProcess.HasExited)
                {
                    session.FfmpegProcess.Kill(true);
                }
            }
            catch { /* Ignore errors on cleanup */ }
            finally
            {
                try { Directory.Delete(Path.Combine(_workspaceRoot, id), true); } catch { }
                _concurrencySemaphore.Release();
            }
            return true;
        }

        private async Task MonitorSessionLifetime(string id, CancellationToken token)
        {
            while (!token.IsCancellationRequested)
            {
                await Task.Delay(TimeSpan.FromMinutes(1), token).ContinueWith(_ => { });
                if (!_sessions.TryGetValue(id, out var session) || DateTime.UtcNow - session.LastAccessed > TimeSpan.FromMinutes(10))
                {
                    Stop(id);
                    break;
                }
            }
        }

        private string CreateHeaderFile(string sessionDir, string apiKey)
        {
            var headerFile = Path.Combine(sessionDir, "headers.txt");
            try
            {
                var authHeader = string.IsNullOrEmpty(apiKey) ? "" : $"X-Emby-Authorization: MediaBrowser Client=\"mosaic-plugin\", Token=\"{apiKey}\"";
                File.WriteAllText(headerFile, authHeader + "\r\n");
            }
            catch (Exception ex)
            {
                throw new InvalidOperationException($"Failed to create header file: {headerFile}", ex);
            }
            return headerFile;
        }

        private string EscapeArg(string s) => s.Replace("\"", "\\\"");

        public void Dispose()
        {
            foreach (var id in _sessions.Keys.ToList()) Stop(id);
            _concurrencySemaphore?.Dispose();
        }
    }
}
