using System;
using System.Collections.Generic;
using RecentChannelsPlugin.Services;
using RecentChannelsPlugin.Data;
using Jellyfin.Data.Enums;
using MediaBrowser.Common.Configuration;
using MediaBrowser.Common.Plugins;
using MediaBrowser.Model.Plugins;
using MediaBrowser.Model.Serialization;
using Microsoft.Extensions.DependencyInjection;

namespace RecentChannelsPlugin
{
    public class Plugin : BasePlugin<PluginConfiguration>, IHasWebPages
    {
        public override string Name => "Recent Channels";
        public override Guid Id => Guid.Parse("12345678-1234-1234-1234-123456789012");
        public override string Description => "Tracks and displays recently watched Live TV channels with TiviMate-style sliding tiles interface";

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
            serviceCollection.AddSingleton<RecentChannelsService>();
            serviceCollection.AddSingleton<RecentChannelsDatabase>();
            serviceCollection.AddSingleton<ViewingTracker>();
            base.ConfigureServices(serviceCollection);
        }
    }

    public class PluginConfiguration : BasePluginConfiguration
    {
        public int MaxRecentChannels { get; set; } = 20;
        public int MinimumWatchTimeSeconds { get; set; } = 30;
        public int HistoryRetentionDays { get; set; } = 30;
        public bool EnableSlidingTiles { get; set; } = true;
        public int TileAutoHideSeconds { get; set; } = 5;
        public bool EnableCrossPlatform { get; set; } = true;
    }
}
