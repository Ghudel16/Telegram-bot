# Telegram GMGN AI Research Bot

Telegram-first AI research agent for GMGN data.

## Architecture

Telegram -> AI Router -> Research Planner -> GMGN tools/API -> Analysis -> Telegram

Secrets are intentionally not stored in GitHub. Configure them as Railway environment variables.

## Planned capabilities

- Natural-language research requests
- Configurable time windows: 24h, 3d, 7d, 10d, 15d, 30d
- ATH market-cap filtering
- Token-level trader/holder research
- Early-holder / ATH-seller analysis when supported by available GMGN data
- 30+ wallet research targets per token
- Cross-token wallet intersection
- Persistent wallet intelligence
- Multi-provider AI routing with fallback
- Optional visualization output
