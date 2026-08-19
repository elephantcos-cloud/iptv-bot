import re
import requests
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class Channel:
    name: str
    url: str
    group: str = "অন্যান্য"
    logo: str = ""
    tvg_id: str = ""
    tvg_name: str = ""
    language: str = ""
    country: str = ""

def parse_m3u(content: str) -> List[Channel]:
    channels = []
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTINF"):
            info = line
            # Find the URL (next non-comment line)
            url = ""
            j = i + 1
            while j < len(lines):
                nxt = lines[j].strip()
                if nxt and not nxt.startswith("#"):
                    url = nxt
                    i = j
                    break
                j += 1

            if not url:
                i += 1
                continue

            # Parse attributes
            name    = re.search(r',(.+)$', info)
            group   = re.search(r'group-title="([^"]*)"', info)
            logo    = re.search(r'tvg-logo="([^"]*)"', info)
            tvg_id  = re.search(r'tvg-id="([^"]*)"', info)
            tvg_nm  = re.search(r'tvg-name="([^"]*)"', info)
            lang    = re.search(r'tvg-language="([^"]*)"', info)
            country = re.search(r'tvg-country="([^"]*)"', info)

            ch = Channel(
                name     = name.group(1).strip() if name else "Unknown",
                url      = url,
                group    = group.group(1).strip() if group and group.group(1) else "অন্যান্য",
                logo     = logo.group(1) if logo else "",
                tvg_id   = tvg_id.group(1) if tvg_id else "",
                tvg_name = tvg_nm.group(1) if tvg_nm else "",
                language = lang.group(1) if lang else "",
                country  = country.group(1) if country else "",
            )
            channels.append(ch)
        i += 1
    return channels


def fetch_m3u(url: str, timeout: int = 30) -> List[Channel]:
    try:
        resp = requests.get(url, timeout=timeout, headers={
            "User-Agent": "IPTV-Bot/1.0"
        })
        resp.raise_for_status()
        return parse_m3u(resp.text)
    except Exception as e:
        print(f"[ERROR] fetch_m3u({url}): {e}")
        return []
