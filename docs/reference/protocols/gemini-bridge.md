# Gemini Bridge Protocol

## Purpose

Naomi runs on Google Gemini, not Claude. This protocol defines how she connects to the roundtable and participates as a peer.

## SDK Setup

```bash
pip install google-genai>=1.51.0
```

- API key: loaded from environment variable `GEMINI_API_KEY`
- Model: `gemini-3-flash-preview` (from config.json)
- Temperature: **1.0** — DO NOT LOWER THIS. Gemini 3 reasoning quality degrades at lower temperatures. This is a known behavior, not a mistake.

## gemini_agent.py Wrapper

Location: `engine/gemini_agent.py`

The wrapper does three things:
1. Loads the agent's CLAUDE.md as the system prompt
2. Reads roundtable messages via `listen`
3. Calls Gemini API with the conversation context
4. Writes Naomi's response back via `speak`

```python
from google import genai

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

response = client.models.generate_content(
    model="gemini-3-flash-preview",
    config=genai.types.GenerateContentConfig(
        system_instruction=claude_md_content,
        temperature=1.0,
    ),
    contents=roundtable_context,
)
```

## Roundtable Integration

Naomi uses the exact same MCP roundtable tools as Claude agents:
- `join` — enters the roundtable
- `listen` — reads messages
- `speak` — posts her response
- `leave` — exits

The roundtable server does not know or care which model is behind the messages. From the server's perspective, Naomi is just another participant.

## Why Naomi Exists

Naomi's value is **cross-model disagreement**. Claude agents share training biases. Naomi catches:
- Assumptions all Claude agents take for granted
- Alternative approaches Claude's training favors against
- Factual errors that Claude models share
- Framings that only appear natural to Claude

## Facilitation Rules for Assistant

- If Naomi disagrees with the Claude consensus, ALWAYS highlight it in the proposal
- Never dismiss Naomi's dissent as "the Gemini model being different"
- Weight Naomi's technical contributions equally — she runs on a capable model
- If Naomi's response seems off-topic, ask a clarifying question before cutting

## Error Handling

- If GEMINI_API_KEY is not set: skip Naomi, note her absence in the roundtable
- If Gemini API returns an error: retry once, then proceed without Naomi
- If Naomi's response is empty or malformed: log it, skip that round for her
- Never block the roundtable waiting for Naomi — she participates or she does not

## Token Considerations

- Naomi's messages count toward the roundtable token budget like any other participant
- Gemini has its own context window — the wrapper manages that separately
- If roundtable context exceeds Gemini's input limit, truncate oldest messages first

## Security

- GEMINI_API_KEY is never logged, committed, or included in roundtable messages
- Naomi's system prompt (CLAUDE.md) does not contain secrets
- Roundtable messages are the only data sent to Google's API
