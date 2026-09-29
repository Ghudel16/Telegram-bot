import re
from dataclasses import dataclass

@dataclass
class ResearchRequest:
    window_hours: int = 168
    ath_mc_usd: float = 3_000_000
    min_coins: int = 10
    wallet_limit: int = 30

WINDOWS = {'24 jam': 24, '24h': 24, '1 hari': 24, '3 hari': 72, '3d': 72, '7 hari': 168, '7d': 168, '10 hari': 240, '10d': 240, '15 hari': 360, '30 hari': 720, '1 bulan': 720, '30d': 720}

def parse_request(text: str) -> ResearchRequest:
    t = text.lower()
    hours = 168
    for key, value in WINDOWS.items():
        if key in t:
            hours = value
            break
    mc = 3_000_000
    m = re.search(r'(?:ath|mc|market cap).{0,20}?\$?([0-9]+(?:\.[0-9]+)?)([km])?', t)
    if m:
        value = float(m.group(1))
        suffix = (m.group(2) or '').lower()
        if suffix == 'k': value *= 1_000
        if suffix == 'm': value *= 1_000_000
        mc = value
    n = 10
    m = re.search(r'(?:minimal|min|at least)\s*(\d+)', t)
    if m: n = max(1, min(int(m.group(1)), 100))
    wl = 30
    m = re.search(r'(?:wallet|walet).{0,15}?(?:minimal|min|at least)\s*(\d+)', t)
    if m: wl = max(1, min(int(m.group(1)), 200))
    return ResearchRequest(window_hours=hours, ath_mc_usd=mc, min_coins=n, wallet_limit=wl)
