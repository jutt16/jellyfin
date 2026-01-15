using System;
using System.Collections.Generic;
using FfmpegMosaicPlugin.Services;
using Jellyfin.Data.Enums;
using MediaBrowser.Common.Configuration;
using MediaBrowser.Common.Plugins;
using MediaBrowser.Model.Plugins;
using MediaBrowser.Model.Serialization;
using Microsoft.Extensions.DependencyInjection;

namespace FfmpegMosaicPlugin
{
    public class Plugin : BasePlugin<PluginConfiguration>, IHasWebPages
    {
        public override string Name => "FFmpeg Mosaic Plugin";
        public override Guid Id => Guid.Parse("a8d394a0-5c63-437e-97d0-8b334a0e23d5");

        public Plugin(IApplicationPaths applicationPaths)
            : base(applicationPaths)
        {
        }

        public IEnumerable<PluginPageInfo> GetPages()
        {
            return new[]
            {
                new PluginPageInfo
                {
                    Name = Name,
                    EmbeddedResourcePath = GetType().Namespace + ".Configuration.config.html"
                }
            };
        }

        public override void ConfigureServices(IServiceCollection serviceCollection)
        {
            serviceCollection.AddSingleton<FfmpegMosaicService>();
            base.ConfigureServices(serviceCollection);
        }
    }

    public class PluginConfiguration : BasePluginConfiguration
    {
        public string WorkspacePath { get; set; } = "";
        public string FfmpegPath { get; set; } = "ffmpeg";
        public int MaxConcurrentMosaics { get; set; } = 3;
        public string WebViewerUrl { get; set; } = "http://localhost:8765";
        public bool AutoStart { get; set; } = false;
    }
}
