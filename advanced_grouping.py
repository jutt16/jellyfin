#!/usr/bin/env python3
"""
Advanced Grouping System for Jellyfin IPTV Manager
Intelligent channel organization by country, category, quality, and custom rules
"""

import re
import json
import logging
from collections import defaultdict
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

@dataclass
class GroupingRule:
    """Represents a grouping rule for channel organization"""
    name: str
    pattern: str
    priority: int = 0
    case_sensitive: bool = False
    regex: bool = False
    target_group: str = ""
    conditions: Dict[str, Any] = None

    def __post_init__(self):
        if self.conditions is None:
            self.conditions = {}

class AdvancedGrouping:
    """Advanced channel grouping with intelligent categorization"""
    
    def __init__(self):
        self.country_patterns = self._load_country_patterns()
        self.category_patterns = self._load_category_patterns()
        self.quality_patterns = self._load_quality_patterns()
        self.custom_rules = []
        
    def _load_country_patterns(self) -> Dict[str, List[str]]:
        """Load country detection patterns"""
        return {
            "USA": ["usa", "us", "united states", "america", "american"],
            "UK": ["uk", "britain", "british", "england", "english", "bbc", "itv"],
            "Canada": ["canada", "canadian", "cbc", "ctv"],
            "France": ["france", "french", "tf1", "france2", "m6"],
            "Germany": ["germany", "german", "deutschland", "ard", "zdf", "rtl"],
            "Italy": ["italy", "italian", "italia", "rai", "mediaset"],
            "Spain": ["spain", "spanish", "españa", "tve", "antena3"],
            "Netherlands": ["netherlands", "dutch", "nederland", "npo"],
            "Belgium": ["belgium", "belgian", "vlaanderen", "rtbf"],
            "Portugal": ["portugal", "portuguese", "rtp", "sic"],
            "Turkey": ["turkey", "turkish", "türkiye", "trt"],
            "Greece": ["greece", "greek", "ert", "mega"],
            "Poland": ["poland", "polish", "polska", "tvp"],
            "Russia": ["russia", "russian", "россия", "первый"],
            "India": ["india", "indian", "hindi", "bollywood", "zee"],
            "Pakistan": ["pakistan", "pakistani", "urdu", "geo"],
            "Arabic": ["arabic", "arab", "العربية", "mbc", "aljazeera"],
            "International": ["international", "world", "global", "multi"]
        }
    
    def _load_category_patterns(self) -> Dict[str, List[str]]:
        """Load category detection patterns"""
        return {
            "News": ["news", "cnn", "bbc news", "fox news", "msnbc", "sky news", "euronews"],
            "Sports": ["sport", "espn", "fox sports", "sky sports", "eurosport", "nba", "nfl", "fifa"],
            "Movies": ["movie", "cinema", "film", "hollywood", "hbo", "starz", "showtime"],
            "Entertainment": ["entertainment", "comedy", "variety", "talk show", "reality"],
            "Kids": ["kids", "children", "cartoon", "disney", "nickelodeon", "cartoon network"],
            "Music": ["music", "mtv", "vh1", "music video", "concert", "radio"],
            "Documentary": ["documentary", "discovery", "national geographic", "history", "science"],
            "Lifestyle": ["lifestyle", "cooking", "travel", "fashion", "home", "garden"],
            "Religious": ["religious", "church", "christian", "islamic", "jewish", "spiritual"],
            "Shopping": ["shopping", "qvc", "hsn", "teleshopping", "home shopping"],
            "Adult": ["adult", "xxx", "18+", "mature", "erotic"],
            "Regional": ["local", "regional", "city", "state", "provincial"]
        }
    
    def _load_quality_patterns(self) -> Dict[str, List[str]]:
        """Load quality detection patterns"""
        return {
            "4K": ["4k", "uhd", "ultra hd", "2160p"],
            "HD": ["hd", "1080p", "1080i", "720p", "high definition"],
            "SD": ["sd", "480p", "576p", "standard definition"],
            "Low": ["240p", "360p", "low quality", "mobile"]
        }
    
    def detect_country(self, channel_name: str, group_title: str = "") -> Optional[str]:
        """Detect country from channel name and group"""
        text = f"{channel_name} {group_title}".lower()
        
        for country, patterns in self.country_patterns.items():
            for pattern in patterns:
                if pattern in text:
                    return country
        
        return None
    
    def detect_category(self, channel_name: str, group_title: str = "") -> Optional[str]:
        """Detect category from channel name and group"""
        text = f"{channel_name} {group_title}".lower()
        
        # Check for explicit category indicators first
        for category, patterns in self.category_patterns.items():
            for pattern in patterns:
                if pattern in text:
                    return category
        
        # Fallback to general categorization
        if any(word in text for word in ["news", "breaking", "live"]):
            return "News"
        elif any(word in text for word in ["sport", "football", "soccer", "basketball"]):
            return "Sports"
        elif any(word in text for word in ["movie", "cinema", "film"]):
            return "Movies"
        
        return "General"
    
    def detect_quality(self, channel_name: str, stream_url: str = "") -> str:
        """Detect quality from channel name and stream URL"""
        text = f"{channel_name} {stream_url}".lower()
        
        for quality, patterns in self.quality_patterns.items():
            for pattern in patterns:
                if pattern in text:
                    return quality
        
        return "Unknown"
    
    def apply_custom_rules(self, channel_data: Dict[str, Any]) -> Dict[str, Any]:
        """Apply custom grouping rules to channel data"""
        result = channel_data.copy()
        
        for rule in sorted(self.custom_rules, key=lambda x: x.priority, reverse=True):
            if self._rule_matches(rule, channel_data):
                if rule.target_group:
                    result['group'] = rule.target_group
                
                # Apply any additional transformations from conditions
                for key, value in rule.conditions.items():
                    if key.startswith('set_'):
                        field = key[4:]  # Remove 'set_' prefix
                        result[field] = value
        
        return result
    
    def _rule_matches(self, rule: GroupingRule, channel_data: Dict[str, Any]) -> bool:
        """Check if a rule matches the channel data"""
        text = channel_data.get('name', '')
        
        if rule.regex:
            pattern = re.compile(rule.pattern, 0 if rule.case_sensitive else re.IGNORECASE)
            if not pattern.search(text):
                return False
        else:
            if rule.case_sensitive:
                if rule.pattern not in text:
                    return False
            else:
                if rule.pattern.lower() not in text.lower():
                    return False
        
        # Check additional conditions
        for condition_key, condition_value in rule.conditions.items():
            if condition_key.startswith('set_'):
                continue  # Skip transformation rules
            
            if condition_key == 'group_contains':
                if condition_value.lower() not in channel_data.get('group', '').lower():
                    return False
            elif condition_key == 'quality_min':
                quality_order = ['Low', 'SD', 'HD', '4K']
                current_quality = self.detect_quality(channel_data.get('name', ''))
                if quality_order.index(current_quality) < quality_order.index(condition_value):
                    return False
        
        return True
    
    def add_custom_rule(self, rule: GroupingRule):
        """Add a custom grouping rule"""
        self.custom_rules.append(rule)
        logger.info(f"Added custom grouping rule: {rule.name}")
    
    def remove_custom_rule(self, rule_name: str) -> bool:
        """Remove a custom grouping rule by name"""
        for i, rule in enumerate(self.custom_rules):
            if rule.name == rule_name:
                del self.custom_rules[i]
                logger.info(f"Removed custom grouping rule: {rule_name}")
                return True
        return False
    
    def organize_channels(self, channels: List[Dict[str, Any]], 
                         grouping_strategy: str = "smart") -> Dict[str, List[Dict[str, Any]]]:
        """Organize channels into groups based on strategy"""
        
        if grouping_strategy == "country":
            return self._group_by_country(channels)
        elif grouping_strategy == "category":
            return self._group_by_category(channels)
        elif grouping_strategy == "quality":
            return self._group_by_quality(channels)
        elif grouping_strategy == "smart":
            return self._smart_grouping(channels)
        else:
            return self._group_by_original(channels)
    
    def _group_by_country(self, channels: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Group channels by detected country"""
        groups = defaultdict(list)
        
        for channel in channels:
            # Apply custom rules first
            channel = self.apply_custom_rules(channel)
            
            country = self.detect_country(channel.get('name', ''), channel.get('group', ''))
            group_name = f"{country} Channels" if country else "International"
            groups[group_name].append(channel)
        
        return dict(groups)
    
    def _group_by_category(self, channels: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Group channels by detected category"""
        groups = defaultdict(list)
        
        for channel in channels:
            # Apply custom rules first
            channel = self.apply_custom_rules(channel)
            
            category = self.detect_category(channel.get('name', ''), channel.get('group', ''))
            groups[category].append(channel)
        
        return dict(groups)
    
    def _group_by_quality(self, channels: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Group channels by detected quality"""
        groups = defaultdict(list)
        
        for channel in channels:
            # Apply custom rules first
            channel = self.apply_custom_rules(channel)
            
            quality = self.detect_quality(channel.get('name', ''))
            group_name = f"{quality} Quality"
            groups[group_name].append(channel)
        
        return dict(groups)
    
    def _smart_grouping(self, channels: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Smart grouping combining multiple strategies"""
        groups = defaultdict(list)
        
        for channel in channels:
            # Apply custom rules first
            channel = self.apply_custom_rules(channel)
            
            # Determine best grouping strategy for this channel
            country = self.detect_country(channel.get('name', ''), channel.get('group', ''))
            category = self.detect_category(channel.get('name', ''), channel.get('group', ''))
            quality = self.detect_quality(channel.get('name', ''))
            
            # Smart grouping logic
            if country and country != "International":
                if category in ["News", "Sports"]:
                    group_name = f"{country} {category}"
                else:
                    group_name = f"{country} Channels"
            elif category and category != "General":
                if quality in ["4K", "HD"]:
                    group_name = f"{category} ({quality})"
                else:
                    group_name = category
            else:
                # Fallback to original group or general
                group_name = channel.get('group', 'General')
            
            groups[group_name].append(channel)
        
        return dict(groups)
    
    def _group_by_original(self, channels: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Keep original grouping but apply custom rules"""
        groups = defaultdict(list)
        
        for channel in channels:
            # Apply custom rules
            channel = self.apply_custom_rules(channel)
            
            group_name = channel.get('group', 'Uncategorized')
            groups[group_name].append(channel)
        
        return dict(groups)
    
    def get_grouping_statistics(self, grouped_channels: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """Get statistics about the grouping results"""
        total_channels = sum(len(channels) for channels in grouped_channels.values())
        
        stats = {
            'total_channels': total_channels,
            'total_groups': len(grouped_channels),
            'groups': {},
            'largest_group': '',
            'smallest_group': '',
            'average_group_size': 0
        }
        
        if grouped_channels:
            for group_name, channels in grouped_channels.items():
                stats['groups'][group_name] = {
                    'count': len(channels),
                    'percentage': (len(channels) / total_channels) * 100 if total_channels > 0 else 0
                }
            
            # Find largest and smallest groups
            group_sizes = [(name, len(channels)) for name, channels in grouped_channels.items()]
            group_sizes.sort(key=lambda x: x[1])
            
            if group_sizes:
                stats['smallest_group'] = group_sizes[0][0]
                stats['largest_group'] = group_sizes[-1][0]
                stats['average_group_size'] = total_channels / len(grouped_channels)
        
        return stats
    
    def save_rules(self, filepath: str):
        """Save custom rules to file"""
        rules_data = [asdict(rule) for rule in self.custom_rules]
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(rules_data, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved {len(self.custom_rules)} custom rules to {filepath}")
    
    def load_rules(self, filepath: str):
        """Load custom rules from file"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                rules_data = json.load(f)
            
            self.custom_rules = []
            for rule_dict in rules_data:
                rule = GroupingRule(**rule_dict)
                self.custom_rules.append(rule)
            
            logger.info(f"Loaded {len(self.custom_rules)} custom rules from {filepath}")
        except FileNotFoundError:
            logger.warning(f"Rules file not found: {filepath}")
        except Exception as e:
            logger.error(f"Failed to load rules from {filepath}: {e}")

# Example usage and predefined rules
def create_default_rules() -> List[GroupingRule]:
    """Create a set of default grouping rules"""
    return [
        GroupingRule(
            name="Premium Sports",
            pattern=r"(espn|fox sports|sky sports)",
            regex=True,
            target_group="Premium Sports",
            priority=10
        ),
        GroupingRule(
            name="News Channels",
            pattern=r"(cnn|bbc|fox news|msnbc)",
            regex=True,
            target_group="International News",
            priority=9
        ),
        GroupingRule(
            name="Kids Content",
            pattern=r"(disney|nickelodeon|cartoon)",
            regex=True,
            target_group="Kids & Family",
            priority=8
        ),
        GroupingRule(
            name="Music Channels",
            pattern=r"(mtv|vh1|music)",
            regex=True,
            target_group="Music & Entertainment",
            priority=7
        ),
        GroupingRule(
            name="Adult Content Filter",
            pattern=r"(xxx|adult|18\+)",
            regex=True,
            target_group="Adult",
            priority=15,
            conditions={"set_restricted": True}
        )
    ]

if __name__ == "__main__":
    # Example usage
    grouping = AdvancedGrouping()
    
    # Add default rules
    for rule in create_default_rules():
        grouping.add_custom_rule(rule)
    
    # Example channels
    sample_channels = [
        {"name": "CNN HD", "group": "News", "url": "http://example.com/cnn"},
        {"name": "ESPN 4K", "group": "Sports", "url": "http://example.com/espn"},
        {"name": "BBC One", "group": "UK", "url": "http://example.com/bbc"},
        {"name": "Disney Channel", "group": "Kids", "url": "http://example.com/disney"}
    ]
    
    # Test different grouping strategies
    for strategy in ["smart", "country", "category", "quality"]:
        print(f"\n=== {strategy.upper()} GROUPING ===")
        grouped = grouping.organize_channels(sample_channels, strategy)
        stats = grouping.get_grouping_statistics(grouped)
        
        for group_name, channels in grouped.items():
            print(f"{group_name}: {len(channels)} channels")
        
        print(f"Statistics: {stats['total_groups']} groups, avg {stats['average_group_size']:.1f} channels/group")
