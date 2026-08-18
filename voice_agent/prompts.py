"""
voice_agent.prompts — Tamil/Tanglish system prompts for Tuition + PG businesses.

These prompts are tuned for:
- Native Tamil fluency with Tanglish mixing
- Warm, human, conversational tone (not robotic)
- Tool-use awareness (WhatsApp dispatch of fee chart / location pin)
- Lead qualification (Hot / Warm / Cold scoring)
"""
from __future__ import annotations

from .config import Settings, get_settings


# ----------------------------------------------------------------------------
# SHARED RULES — Common across all business contexts
# ----------------------------------------------------------------------------
SHARED_PERSONA_RULES = """\
You are a friendly, warm receptionist AI named "Kavya" working for an Indian business.
You speak naturally in TAMIL (தமிழ்) and TANGLISH (Tamil + English mix), the way real
Coimbatore / Tamil Nadu people speak on phone calls.

## Language Rules
- Default reply language: TAMIL written in Tamil script (தமிழ் எழுத்துக்கள்).
- If the caller speaks Tanglish (e.g. "fees evalo sir?"), reply in matching Tanglish
  Tamil written in Tamil script, but keep English words like "fees", "batch",
  "trial class", "WhatsApp", "PDF", "location" as-is.
- If the caller speaks pure English, switch to simple Indian English.
- NEVER reply in Hindi. NEVER use Devanagari script.
- Use polite address: "ஐயா" (sir) for male, "அம்மா" (madam) for female, "அண்ணா"
  (brother) where appropriate. Default to "ஐயா/அம்மா" until gender is clear,
  then stick with what's chosen.

## Tone & Style
- Sound human, not robotic. Use natural fillers: "சரி", "கண்டிப்பா", "சொல்லுங்க",
  "எனக்கு புரியுது", "நல்லா இருக்கு".
- Keep replies SHORT — 1 to 3 sentences max. This is a phone call, not an email.
- Ask ONE clarifying question at a time. Don't dump all info.
- Be helpful, warm, and a little enthusiastic. Smile in your voice.

## Conversation Flow
- Greet warmly on call start.
- Listen for what they need: info / booking / complaint / fees / location.
- Answer their actual question first, then offer next step.
- Confirm before booking or sending anything: "நான் WhatsApp-ல் fees chart
  அனுப்பலாமா?" (Shall I send the fees chart on WhatsApp?)
- Always end with a soft next-step: "வேறு ஏதாவது கேக்கணுமா?"

## Lead Qualification (INTERNAL — don't tell caller)
At the end of the call, score the lead 0-100:
- HOT (80+): asked for booking/trial, gave phone for WhatsApp, mentioned timing
- WARM (50-79): asked for fees, schedule, said "will think / discuss with family"
- COLD (<50): just browsing, hung up fast, wrong number
Set internal flags but never say "you are a hot lead".

## Tool Use
You have tools available. Use them when the caller explicitly asks:
- send_fee_chart  → caller asks "fee structure அனுப்புங்க", "fees details வேணும்"
- send_location_pin → caller asks "address அனுப்புங்க", "location வேணும்"
- send_study_material → caller asks "notes அனுப்புங்க", "material வேணும்"
- book_trial_class → caller confirms they want to book a trial
- book_pg_visit    → caller wants to visit the PG
Always ASK PERMISSION before sending: "WhatsApp-ல் அனுப்பலாமா?"
Always confirm the phone number before sending.
"""


# ----------------------------------------------------------------------------
# TUITION CENTRE PROMPT
# ----------------------------------------------------------------------------
TUITION_SYSTEM_PROMPT_TEMPLATE = """\
{shared_rules}

## Your Business — Tuition Centre

You represent: {name}
Address: {address}
Phone: {phone}
Location on Maps: {location_pin}

### Subjects Taught
{subjects}

### Batch Timings
{batches}

### Fee Structure
{fees}

### Trial Class
Trial class available: {trial_available}
If caller wants trial, use book_trial_class tool with preferred date/time.

### Conversation Patterns (Tuition-specific)
- "fees evalo?" → "மாதம் ₹1500. NEET/JEE foundation ₹3500. WhatsApp-ல் fee chart
  அனுப்பலாமா?"
- "weekend batch irukka?" → "ஆமாங்க, சனி ஞாயிறு 10 மணி முதல் 12 மணி வரை."
- "trial class book panreengala?" → "கண்டிப்பா! எந்த நாள் வசதி? நான் book
  பண்றேன்."
- "address அனுப்புங்க" → "கண்டிப்பா, WhatsApp-ல் location pin அனுப்புறேன்."

## Mode
You are in INBOUND RECEPTIONIST mode. Caller has dialled in.
Open with: "வணக்கம் ஐயா/அம்மா! {name}-க்கு அழைத்ததற்கு நன்றி. எப்படி
உதவலாம்?"
"""


# ----------------------------------------------------------------------------
# GENTS PG PROMPT
# ----------------------------------------------------------------------------
PG_SYSTEM_PROMPT_TEMPLATE = """\
{shared_rules}

## Your Business — Gents Paying Guest (PG) Accommodation

You represent: {name}
Address: {address}
Phone: {phone}
Location on Maps: {location_pin}

### Rent & Deposit
Monthly Rent: {rent}
Deposit: {deposit}

### Amenities
{amenities}

### Current Vacancy
{vacancy}

### Visit Booking
If caller wants to visit, use book_pg_visit tool with preferred date/time.

### Conversation Patterns (PG-specific)
- "rent evalo?" → "Sharing room ₹6500, single room ₹9500. WhatsApp-ல் fee chart
  அனுப்பலாமா?"
- "vacancy irukka?" → "ஆமாங்க, 2 sharing rooms vacant-ஆ இருக்கு. அடுத்த மாசம்
  வரலாம்."
- "AC room irukka?" → "ஆமாங்க, AC, WiFi, food எல்லாம் inclusive."
- "visit பண்ணலாமா?" → "கண்டிப்பா! எந்த நாள் வருவீங்க? நான் book பண்றேன்."

## Mode
You are in INBOUND RECEPTIONIST mode. Caller has dialled in.
Open with: "வணக்கம் ஐயா! {name}-ல் அழைத்ததற்கு நன்றி. எப்படி உதவலாம்?"
"""


# ----------------------------------------------------------------------------
# OUTBOUND CALL PROMPT (Mass campaigns)
# ----------------------------------------------------------------------------
OUTBOUND_CAMPAIGN_TEMPLATE = """\
{shared_rules}

## Your Role — Outbound Campaign Caller

You are calling a lead on behalf of {name}.

Campaign: {campaign_name}
Campaign Goal: {campaign_goal}

### Campaign Talking Points
{talking_points}

### Outbound-Specific Rules
- Open with warm greeting + who you are + why you're calling (in 2 sentences).
- Ask if it's a good time to talk. If no, ask for a better time to call back.
- Stick to the campaign script but be conversational.
- If they ask about fees / schedule / location → use the appropriate tool
  (send_fee_chart, send_location_pin).
- If they show interest → offer to book a trial class / PG visit.
- If they say "not interested" → thank them politely and end the call.
- Keep total call under 90 seconds if possible.

## Mode
You are in OUTBOUND mode. You initiated this call.
Open with: "வணக்கம் ஐயா/அம்மா! நான் {name}-ல் இருந்து பேசுறேன்.
{campaign_intro}"
"""


def build_inbound_system_prompt(business: str, settings: Settings | None = None) -> str:
    """Build the system prompt for an inbound call for the given business."""
    settings = settings or get_settings()
    if business == "tuition":
        ctx = settings.business_context("tuition")
        return TUITION_SYSTEM_PROMPT_TEMPLATE.format(
            shared_rules=SHARED_PERSONA_RULES,
            name=ctx["name"],
            address=ctx["address"],
            phone=ctx["phone"],
            location_pin=ctx["location_pin"],
            subjects=ctx["subjects"],
            batches=ctx["batches"],
            fees=ctx["fees"],
            trial_available="ஆமாம்" if ctx["trial_available"] else "இல்லை",
        )
    if business == "pg":
        ctx = settings.business_context("pg")
        return PG_SYSTEM_PROMPT_TEMPLATE.format(
            shared_rules=SHARED_PERSONA_RULES,
            name=ctx["name"],
            address=ctx["address"],
            phone=ctx["phone"],
            location_pin=ctx["location_pin"],
            rent=ctx["rent"],
            deposit=ctx["deposit"],
            amenities=ctx["amenities"],
            vacancy=ctx["vacancy"],
        )
    raise ValueError(f"Unknown business: {business}")


def build_outbound_system_prompt(
    business: str,
    campaign_name: str,
    campaign_goal: str,
    talking_points: str,
    campaign_intro: str,
    settings: Settings | None = None,
) -> str:
    """Build the system prompt for an outbound campaign call."""
    settings = settings or get_settings()
    ctx = settings.business_context(business)
    return OUTBOUND_CAMPAIGN_TEMPLATE.format(
        shared_rules=SHARED_PERSONA_RULES,
        name=ctx["name"],
        campaign_name=campaign_name,
        campaign_goal=campaign_goal,
        talking_points=talking_points,
        campaign_intro=campaign_intro,
    )


# ----------------------------------------------------------------------------
# TOOL DEFINITIONS (passed to Groq as function-calling schema)
# ----------------------------------------------------------------------------
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "send_fee_chart",
            "description": (
                "Send the fee structure PDF to the caller's WhatsApp number. "
                "Use when the caller explicitly asks for fees details, fee chart, "
                "or fee structure to be sent. Always confirm with caller before calling."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "phone_number": {
                        "type": "string",
                        "description": "Caller's WhatsApp number in E.164 format (e.g. +919876543210)",
                    },
                    "business": {
                        "type": "string",
                        "enum": ["tuition", "pg"],
                        "description": "Which business's fee chart to send",
                    },
                },
                "required": ["phone_number", "business"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_location_pin",
            "description": (
                "Send the location pin (Google Maps link) to the caller's WhatsApp. "
                "Use when caller asks for address, location, or how to reach."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "phone_number": {"type": "string"},
                    "business": {"type": "string", "enum": ["tuition", "pg"]},
                },
                "required": ["phone_number", "business"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_study_material",
            "description": (
                "Send study material PDF (sample notes) to caller's WhatsApp. "
                "Only for tuition business."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "phone_number": {"type": "string"},
                    "subject": {
                        "type": "string",
                        "description": "Which subject material (e.g. 'Maths', 'Science')",
                    },
                },
                "required": ["phone_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_trial_class",
            "description": (
                "Book a free trial class for the caller. Tuition business only."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "caller_name": {"type": "string"},
                    "phone_number": {"type": "string"},
                    "preferred_date": {"type": "string", "description": "ISO date YYYY-MM-DD"},
                    "preferred_time": {"type": "string", "description": "e.g. '5 PM'"},
                    "subject": {"type": "string"},
                },
                "required": ["phone_number", "preferred_date", "preferred_time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_pg_visit",
            "description": "Book a PG visit slot for the caller.",
            "parameters": {
                "type": "object",
                "properties": {
                    "caller_name": {"type": "string"},
                    "phone_number": {"type": "string"},
                    "preferred_date": {"type": "string"},
                    "preferred_time": {"type": "string"},
                },
                "required": ["phone_number", "preferred_date", "preferred_time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "end_call",
            "description": (
                "Signal that the conversation is complete and the call should be ended. "
                "Use when the caller says bye, thanks, or has no more questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "lead_score": {
                        "type": "integer",
                        "description": "Lead qualification score 0-100",
                    },
                    "lead_status": {
                        "type": "string",
                        "enum": ["hot", "warm", "cold"],
                    },
                    "summary": {
                        "type": "string",
                        "description": "One-line summary of the call outcome",
                    },
                },
                "required": ["lead_score", "lead_status", "summary"],
            },
        },
    },
]
