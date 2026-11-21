---
{
  "id": "distribution",
  "version": 1,
  "vars": ["date", "filename", "headline", "next_line", "prelim", "footer", "channels"],
  "when": [
    {"if": "tier == lite", "use": "lite.md"},
    {"if": "tier == standard", "use": "standard.md"},
    {"if": "tier == strategic", "use": "strategic.md"}
  ],
  "fragments": [
    {"id": "chat-dm", "when": "tier in ['standard', 'strategic']", "file": "fragments/chat-dm.md", "budget": 10},
    {"id": "mail-agenda", "when": "tier == strategic", "file": "fragments/mail-agenda.md", "budget": 10},
    {"id": "video-script", "when": "video == requested", "file": "fragments/video-script.md", "budget": 6}
  ],
  "default": "lite.md",
  "budget": {"max_lines": 60, "max_vars": 8},
  "dedupe": {"prelim": "headline"}
}
---
