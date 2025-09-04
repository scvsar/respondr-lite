# Mission Simulator

A standalone tool for simulating realistic SAR missions to test Azure infrastructure costs and performance.

## Features

- **Realistic Mission Scenarios**: Simulates actual Snohomish County SAR locations (Lake 22, Lake Serene, Wallace Falls, etc.)
- **Authentic Responders**: Generates 15-25 responders with realistic names and behavior patterns
- **Natural Message Generation**: Uses GPT-5-nano to create authentic-sounding SAR messages
- **Realistic Timing**: Simulates actual mission cadence with initial response flood, follow-ups, and late updates
- **Cost Testing**: Sends real webhook messages to test Azure infrastructure under load

## Setup

1. Install dependencies:
   ```bash
   pip install -r simulator_requirements.txt
   ```

2. Configure environment variables (copy `.env.example` to `.env` and fill in values):
   ```bash
   cp .env.example .env
   # Edit .env with your actual endpoints and API keys
   ```

## Usage

### Test Mode (Dry Run)
```bash
python mission_simulator.py --dry-run
```
Shows what messages would be sent without actually sending them.

### Force Start Mission
```bash
python mission_simulator.py --force-mission
```
Starts a mission immediately regardless of timing.

### Normal Operation
```bash
python mission_simulator.py
```
Checks if 48+ hours have passed since the last mission and starts one if needed.

## Mission Flow

1. **Mission Alert**: Sends realistic RAVE alert (e.g., "PACKOUT LAKE 22. 45YM SEVERE LEG LACERATION...")
2. **Initial Responses** (0-10 minutes): Flood of responder messages with vehicles and ETAs
3. **Follow-up Phase** (10-30 minutes): Questions about logistics, parking, equipment
4. **Late Updates** (30+ minutes): Status updates, cancellations, delays

## Responder Characteristics

- **Experience Levels**: Rookie (40% response rate), Experienced (70%), Veteran (90%)
- **Personalities**: Precise, Casual, Talkative, Quiet - affects message style
- **Vehicle Preferences**: POV (most common), SAR vehicles, SAR Rig
- **Realistic Behavior**: Some cancel, some ask questions, some send multiple updates

## Message Examples

**Initial Responses:**
- "Mike responding POV ETA 45 min"
- "Sarah SAR-23 eta 1630"
- "Chris en route POV ETA 1 hr"

**Follow-ups:**
- "Park at trailhead?"
- "Anyone bringing extra water?"
- "Meet at TL if you want to carpool"

**Updates:**
- "At TH now, heading up"
- "Sorry, have to cancel - work emergency"
- "Stuck in traffic, running 10 min late"

## Deployment

Can be deployed as:
- **Azure Function**: Triggered on schedule (every 48 hours)
- **GitHub Action**: Runs on cron schedule
- **Local Cron**: Run periodically from a server
- **Manual**: Run as needed for testing

## Cost Testing

The simulator helps estimate Azure costs by:
- Generating realistic message volumes (20-60 messages per mission)
- Testing webhook processing under load
- Exercising AI processing with authentic message patterns
- Simulating real mission timing patterns

## Configuration

Key settings in `mission_simulator.py`:
- `PREPROD_GROUP_ID`: Uses PreProd group (109174633) for testing
- `message_history_hours`: 12-hour window for message history
- `max_responders`: 15-25 responders per mission
- Response phases with realistic timing

## Safety

- Uses PreProd group ID by default to avoid disrupting real operations
- Includes dry-run mode for testing
- Generates fake but realistic responder IDs
- Does not interfere with actual SAR operations