using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Threading;

namespace FfmpegMosaicPlugin.Models
{
    public class MosaicSession
    {
        public string Id { get; set; } = Guid.NewGuid().ToString("n");
        public string OwnerUserId { get; set; }
        public List<string> ChannelIds { get; set; } = new();
        public Dictionary<string, string> InputUrls { get; set; } = new();
        public Dictionary<string, string> ChannelNames { get; set; } = new();
        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
        public string OutputRelativePath { get; set; } = "";
        public int BitrateK { get; set; } = 4000;
        public int TileW { get; set; } = 640;
        public int TileH { get; set; } = 360;
        public int OutW { get; set; } = 1280;
        public int OutH { get; set; } = 720;
        public DateTime LastAccessed { get; set; } = DateTime.UtcNow;
        public Process FfmpegProcess { get; set; }
        public CancellationTokenSource Cts { get; set; }
    }
}
