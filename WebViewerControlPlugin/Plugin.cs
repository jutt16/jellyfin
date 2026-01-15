using System;
using MediaBrowser.Common.Configuration;
using MediaBrowser.Common.Plugins;
using MediaBrowser.Model.Plugins;
using MediaBrowser.Model.Serialization;

namespace WebViewerControlPlugin
{
    public class Plugin : BasePlugin<PluginConfiguration>, IHasWebPages
    {
        public override string Name => "Web Viewer Control";
        public override Guid Id => Guid.Parse("b8d394a0-5c63-437e-97d0-8b334a0e23d6");

        public Plugin(IApplicationPaths applicationPaths, IXmlSerializer xmlSerializer)
            : base(applicationPaths, xmlSerializer)
        {
        }

        public IEnumerable<PluginPageInfo> GetPages()
        {
            return new[]
            {
                new PluginPageInfo
                {
                    Name = "Web Viewer Control",
                    EmbeddedResourcePath = GetType().Namespace + ".Configuration.webviewer.html"
                }
            };
        }
    }

    public class PluginConfiguration : BasePluginConfiguration
    {
        public string WebViewerUrl { get; set; } = "http://localhost:8765";
        public bool AutoStart { get; set; } = false;
    }
}
