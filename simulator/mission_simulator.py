#!/usr/bin/env python3
"""
Mission Simulator for Respondr Lite

Generates realistic SAR mission scenarios with authentic responder messages
to test the cost and performance of the Azure infrastructure.

Usage:
    python mission_simulator.py [--dry-run] [--force-mission]
"""

import json
import random
import time
import requests
import logging
import math
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import argparse
import os
from openai import AzureOpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration
# Real SAR Team Group IDs
REAL_GROUP_IDS = {
    "97608845": "4X4",
    "6846970": "ASAR", 
    "61402638": "ASAR",
    "19723040": "SSAR",
    "96018206": "IMT",
    "1596896": "K9",
    "92390332": "ASAR",
    "99606944": "OSU",
    "14533239": "MSAR",
    "106549466": "ESAR",
    "16649586": "OSU"
}

AZURE_FUNCTION_ENDPOINT = os.getenv("AZURE_FUNCTION_ENDPOINT", "https://respondrliteapp-d5614dea.azurewebsites.net")
WEBHOOK_API_KEY = os.getenv("WEBHOOK_API_KEY")
PREPROD_WEB_ENDPOINT = os.getenv("PREPROD_WEB_ENDPOINT", "https://preprod.scvsar.app")

# Authentication for keepalive
LOCAL_USER_NAME = os.getenv("LOCAL_USER_NAME")
LOCAL_USER_PASSWORD = os.getenv("LOCAL_USER_PASSWORD")

# GPT-5-nano configuration for natural message generation
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_DEPLOYMENT = "gpt-5-nano"  # or whatever the deployment name is

@dataclass
class MissionLocation:
    """Represents a SAR mission location"""
    name: str
    coordinates: Tuple[float, float]  # (lat, lon)
    trail_description: str
    typical_scenarios: List[str]

@dataclass
class Responder:
    """Represents a SAR responder"""
    name: str
    user_id: str
    sender_id: str
    experience_level: str  # "rookie", "experienced", "veteran"
    response_probability: float  # 0.0 to 1.0
    vehicle_preference: str  # "POV", "SAR-X", "SAR Rig"
    personality: str  # "precise", "casual", "talkative", "quiet"
    group_id: str = "6846970"  # Default to ASAR if not specified

class MissionSimulator:
    """Simulates realistic SAR missions with authentic message patterns"""
    
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.openai_client = None
        self._init_openai()
        
        # Mission tracking
        self.current_mission = None
        self.message_history = []
        self.keepalive_stop_event = threading.Event()
        self.mission_start_time = None
        
        # Authentication
        self.auth_token = None
        
        # Mission group assignment
        self.current_mission_group_id = None
        
    def _init_openai(self):
        """Initialize OpenAI client for natural message generation"""
        if AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT:
            try:
                self.openai_client = AzureOpenAI(
                    api_key=AZURE_OPENAI_API_KEY,
                    api_version="2024-02-01",
                    azure_endpoint=AZURE_OPENAI_ENDPOINT,
                )
                logger.info("OpenAI client initialized for message generation")
            except Exception as e:
                logger.warning(f"Failed to initialize OpenAI client: {e}")
    
    def _authenticate(self) -> bool:
        """Authenticate with the web application to get an access token."""
        if not LOCAL_USER_NAME or not LOCAL_USER_PASSWORD:
            logger.warning("No local authentication credentials found in environment")
            return False
            
        if self.dry_run:
            logger.info("[DRY RUN] Would authenticate with local user")
            self.auth_token = "dry-run-token"
            return True
            
        try:
            response = requests.post(
                f"{PREPROD_WEB_ENDPOINT}/api/auth/local/login",
                json={
                    "username": LOCAL_USER_NAME,
                    "password": LOCAL_USER_PASSWORD
                },
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("success") and data.get("token"):
                    self.auth_token = data["token"]
                    logger.info(f"✓ Authenticated as {LOCAL_USER_NAME}")
                    return True
                else:
                    logger.error(f"Login failed: {data.get('error', 'Unknown error')}")
                    return False
            else:
                logger.error(f"Login request failed with status {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            return False
    
    def _select_mission_group(self) -> str:
        """Select a random Group ID for this mission"""
        group_id = random.choice(list(REAL_GROUP_IDS.keys()))
        team_name = REAL_GROUP_IDS[group_id]
        self.current_mission_group_id = group_id
        logger.info(f"Selected mission group: {team_name} (ID: {group_id})")
        return group_id
    
    @property
    def snohomish_locations(self) -> List[MissionLocation]:
        """Popular SAR locations in Snohomish County"""
        return [
            MissionLocation(
                "Lake 22 Trail", 
                (48.0767, -121.7843),
                "2.7 mile trail to alpine lake",
                ["injured hiker", "lost hiker", "medical emergency", "hypothermia"]
            ),
            MissionLocation(
                "Lake Serene Trail",
                (47.8165, -121.5789),
                "4.5 mile trail with waterfall views",
                ["slip and fall", "cardiac event", "lost party", "stuck climber"]
            ),
            MissionLocation(
                "Wallace Falls",
                (47.8710, -121.6776),
                "Popular waterfall hike",
                ["ankle injury", "heat exhaustion", "lost child", "dog rescue"]
            ),
            MissionLocation(
                "Heather Lake",
                (48.0589, -121.7935),
                "1.5 mile hike to subalpine lake",
                ["severe laceration", "broken bone", "altitude sickness", "stuck hiker"]
            ),
            MissionLocation(
                "Mount Pilchuck",
                (48.0709, -121.8165),
                "Steep 3-mile trail to fire lookout",
                ["fall from rocks", "weather exposure", "lost in fog", "equipment failure"]
            ),
            MissionLocation(
                "Gothic Basin",
                (48.0845, -121.4367),
                "Challenging backcountry access",
                ["rockfall injury", "stream crossing accident", "overnight rescue", "weather emergency"]
            )
        ]
    
    @property
    def realistic_responders(self) -> List[Responder]:
        """Generate pool of realistic SAR responders"""
        first_names = [
            "Mike", "Sarah", "David", "Jessica", "Chris", "Amanda", "Ryan", "Lisa", 
            "Kevin", "Jennifer", "Mark", "Emily", "Jason", "Ashley", "Brian", "Michelle",
            "Steve", "Nicole", "Matt", "Stephanie", "Dan", "Rachel", "Tom", "Melissa",
            "John", "Amy", "Rob", "Heather", "Scott", "Katie", "Jim", "Lindsey",
            "Paul", "Kristen", "Ben", "Angela", "Adam", "Samantha", "Jake", "Brittany"
        ]
        
        last_names = [
            "Anderson", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
            "Wilson", "Martinez", "Taylor", "Thomas", "Jackson", "White", "Harris", "Martin",
            "Thompson", "Moore", "Young", "Allen", "King", "Wright", "Lopez", "Hill",
            "Green", "Adams", "Baker", "Nelson", "Carter", "Mitchell", "Perez", "Roberts",
            "Turner", "Phillips", "Campbell", "Parker", "Evans", "Edwards", "Collins", "Stewart"
        ]
        
        responders = []
        for i in range(50):  # Pool of 50 potential responders
            first = random.choice(first_names)
            last = random.choice(last_names)
            name = f"{first} {last}"
            
            # Generate realistic IDs (similar format to GroupMe)
            user_id = str(random.randint(100000000, 999999999))
            sender_id = str(random.randint(100000000, 999999999))
            
            # Assign characteristics
            experience = random.choices(
                ["rookie", "experienced", "veteran"],
                weights=[0.3, 0.5, 0.2]
            )[0]
            
            # Response probability based on experience
            prob_map = {"rookie": 0.4, "experienced": 0.7, "veteran": 0.9}
            response_prob = prob_map[experience] + random.uniform(-0.1, 0.1)
            response_prob = max(0.2, min(0.95, response_prob))
            
            # Vehicle preference
            if experience == "veteran":
                vehicle = random.choices(
                    ["POV", f"SAR-{random.randint(1, 99)}", "SAR Rig"],
                    weights=[0.3, 0.6, 0.1]
                )[0]
            else:
                vehicle = random.choices(
                    ["POV", f"SAR-{random.randint(1, 99)}"],
                    weights=[0.8, 0.2]
                )[0]
            
            personality = random.choice(["precise", "casual", "talkative", "quiet"])
            
            responders.append(Responder(
                name=name,
                user_id=user_id,
                sender_id=sender_id,
                experience_level=experience,
                response_probability=response_prob,
                vehicle_preference=vehicle,
                personality=personality
            ))
        
        return responders
    
    def generate_mission_alert(self, location: MissionLocation) -> str:
        """Generate initial RAVE alert message"""
        scenario = random.choice(location.typical_scenarios)
        
        # Age and gender
        age = random.randint(18, 75)
        gender = random.choice(["M", "F"])
        
        # Injury details based on scenario
        injury_details = {
            "injured hiker": ["ankle fracture", "leg laceration", "head trauma", "back injury"],
            "lost hiker": ["disoriented", "hypothermic", "dehydrated", "phone dead"],
            "medical emergency": ["cardiac event", "diabetic emergency", "seizure", "allergic reaction"],
            "slip and fall": ["broken wrist", "concussion", "shoulder dislocation", "multiple lacerations"],
            "severe laceration": ["deep cut", "arterial bleeding", "needs sutures", "on blood thinners"],
            "broken bone": ["compound fracture", "cannot bear weight", "severe pain", "possible internal bleeding"]
        }
        
        detail = random.choice(injury_details.get(scenario, ["injured", "needs assistance"]))
        
        # SAR IC phone number (realistic format)
        ic_phone = f"425{random.randint(1000000, 9999999)}"
        
        # Mission types
        mission_type = random.choice(["PACKOUT", "TRANSPORT", "SEARCH", "RESCUE"])
        
        alert = f"{mission_type} {location.name.upper()}. {age}Y{gender} {detail.upper()} {random.choice(['CANT WALK', 'NEEDS IMMEDIATE EVAC', 'UNABLE TO CONTINUE', 'REQUIRES ASSISTANCE'])}. {location.trail_description.upper()}. SAR{random.randint(1, 15)} IC {ic_phone}. {location.coordinates[0]:.4f},{location.coordinates[1]:.4f}."
        
        return alert
    
    def generate_natural_message(self, responder: Responder, context: str, message_type: str, current_time: datetime = None) -> str:
        """Use GPT-5-nano to generate natural-sounding messages"""
        if current_time is None:
            current_time = datetime.now()
            
        if not self.openai_client:
            # Fallback to template-based generation
            return self._generate_template_message(responder, message_type, current_time)
        
        try:
            personality_prompts = {
                "precise": "You are a precise, professional SAR responder who uses clear, concise language.",
                "casual": "You are a casual, friendly SAR responder who uses informal language and contractions.",
                "talkative": "You are an experienced, talkative SAR responder who provides extra details.",
                "quiet": "You are a quiet, efficient SAR responder who keeps messages brief."
            }
            
            message_type_prompts = {
                "initial_response": f"Respond to the SAR mission with your availability, vehicle, and ETA. Your vehicle preference is {responder.vehicle_preference}.",
                "followup_question": "Ask a quick logistical question about parking, meeting location, or equipment.",
                "status_update": "Provide a brief status update about your progress or situation.",
                "cancellation": "Unfortunately need to cancel your response due to an unexpected issue."
            }
            
            prompt = f"""
            {personality_prompts.get(responder.personality, '')}
            
            Context: SAR mission response in progress. {context}
            
            Task: {message_type_prompts.get(message_type, 'Send a SAR response message.')}
            
            Keep the message realistic and under 20 words. Use common SAR terminology and abbreviations.
            Your name is {responder.name.split()[0]}.
            
            Generate only the message text, no quotes or extra formatting.
            """
            
            # Try with full parameters first
            kwargs = {
                "model": AZURE_OPENAI_DEPLOYMENT,
                "messages": [{"role": "user", "content": prompt}],
                "max_completion_tokens": 50,
                "temperature": 1,
                "top_p": 1,
            }
            
            response = self.openai_client.chat.completions.create(**kwargs)
            message = response.choices[0].message.content.strip()
            return message
            
        except Exception as e:
            # Handle unsupported parameters like the backend does
            error_text = str(e).lower()
            if "unsupported parameter" in error_text or "not supported" in error_text:
                logger.info("Retrying with minimal parameters due to unsupported parameter error")
                try:
                    # Retry with minimal parameters
                    response = self.openai_client.chat.completions.create(
                        model=AZURE_OPENAI_DEPLOYMENT,
                        messages=[{"role": "user", "content": prompt}],
                        max_completion_tokens=50
                    )
                    message = response.choices[0].message.content.strip()
                    return message
                except Exception as e2:
                    logger.warning(f"Failed to generate natural message even with minimal params: {e2}")
            else:
                logger.warning(f"Failed to generate natural message: {e}")
            
            return self._generate_template_message(responder, message_type, current_time)
    
    def _generate_template_message(self, responder: Responder, message_type: str, current_time: datetime = None) -> str:
        """Fallback template-based message generation"""
        if current_time is None:
            current_time = datetime.now()
            
        first_name = responder.name.split()[0]
        
        if message_type == "initial_response":
            templates = [
                f"{first_name} responding {responder.vehicle_preference} ETA {self._random_eta(current_time)}",
                f"Responding {responder.vehicle_preference} eta {self._random_eta(current_time)}",
                f"{first_name} {responder.vehicle_preference} {self._random_eta(current_time)}",
                f"En route {responder.vehicle_preference} ETA {self._random_eta(current_time)}",
                f"Responding, taking {responder.vehicle_preference}, eta {self._random_eta(current_time)}"
            ]
        elif message_type == "followup_question":
            templates = [
                "Park at trailhead?",
                "Meeting at TH or somewhere else?",
                "Anyone need extra gear?",
                "Should I bring the litter?",
                "Meet at Taylor's Landing if you want to carpool",
                "Bringing extra water and first aid",
                "Traffic is heavy, might be 10 min late",
                "Anyone have cell service up there?"
            ]
        elif message_type == "status_update":
            templates = [
                f"At TH now, heading up",
                f"30 min out",
                f"Just left, should be there soon",
                f"Stuck in traffic, running late",
                f"Almost there"
            ]
        elif message_type == "cancellation":
            templates = [
                f"Sorry, have to cancel - work emergency",
                f"Can't make it, family situation",
                f"Vehicle trouble, backing out",
                f"Called back to work, sorry",
                f"Sick kid, have to cancel"
            ]
        else:
            templates = [f"{first_name} responding {responder.vehicle_preference}"]
        
        return random.choice(templates)
    
    def _random_eta(self, current_time: datetime) -> str:
        """Generate realistic ETA based on current time and mission context"""
        if not self.mission_start_time:
            self.mission_start_time = current_time
            
        # Calculate realistic arrival times (15 minutes to 3 hours from now)
        minutes_from_now = random.randint(15, 180)  # 15 minutes to 3 hours
        eta_time = current_time + timedelta(minutes=minutes_from_now)
        
        # Various ETA formats
        format_choice = random.random()
        
        if format_choice < 0.4:  # 40% - duration format
            if minutes_from_now < 60:
                return f"{minutes_from_now} min"
            else:
                hours = minutes_from_now // 60
                remaining_mins = minutes_from_now % 60
                if remaining_mins == 0:
                    return f"{hours} hr"
                else:
                    return f"{hours}:{remaining_mins:02d}"
        else:  # 60% - clock time format
            # Use 24-hour format sometimes, 12-hour format others
            if random.random() < 0.7:  # 70% use 24-hour
                return f"{eta_time.hour:02d}{eta_time.minute:02d}"
            else:  # 30% use hour:minute format
                return f"{eta_time.hour}:{eta_time.minute:02d}"
    
    def should_start_mission(self) -> bool:
        """Check if it's time to start a new mission (every ~48 hours)"""
        # In a real implementation, this would check the last mission timestamp
        # from your storage backend. For simulation, we'll use a simple time-based check
        
        last_mission_file = "last_mission.txt"
        try:
            if os.path.exists(last_mission_file):
                with open(last_mission_file, 'r') as f:
                    last_time = float(f.read().strip())
                    hours_since = (time.time() - last_time) / 3600
                    return hours_since >= 48
            else:
                return True  # No previous mission, start one
        except:
            return True
    
    def update_last_mission_time(self):
        """Update the last mission timestamp"""
        with open("last_mission.txt", 'w') as f:
            f.write(str(time.time()))
    
    def start_website_keepalive(self):
        """Start background thread to keep website warm during mission"""
        def keepalive_worker():
            logger.info("Starting website keepalive (2 hours)")
            start_time = time.time()
            max_duration = 2 * 60 * 60  # 2 hours in seconds
            
            while not self.keepalive_stop_event.is_set():
                elapsed = time.time() - start_time
                if elapsed >= max_duration:
                    logger.info("Website keepalive completed (2 hours elapsed)")
                    break
                
                try:
                    if self.dry_run:
                        logger.info("[DRY RUN] Would ping /api/responders")
                    else:
                        headers = {"User-Agent": "Mission-Simulator-Keepalive/1.0"}
                        if self.auth_token:
                            headers["Authorization"] = f"Bearer {self.auth_token}"
                            
                        response = requests.get(
                            f"{PREPROD_WEB_ENDPOINT}/api/responders",
                            timeout=30,
                            headers=headers
                        )
                        if response.status_code == 200:
                            logger.info(f"✓ Website keepalive ping successful ({len(response.json().get('responders', []))} responders)")
                        else:
                            logger.warning(f"Website keepalive ping returned {response.status_code}")
                except Exception as e:
                    logger.warning(f"Website keepalive ping failed: {e}")
                
                # Wait 2-3 minutes before next ping (randomized to avoid perfect intervals)
                wait_time = random.uniform(120, 180)  # 2-3 minutes
                if self.keepalive_stop_event.wait(wait_time):
                    break
            
            logger.info("Website keepalive stopped")
        
        keepalive_thread = threading.Thread(target=keepalive_worker, daemon=True)
        keepalive_thread.start()
        return keepalive_thread
    
    def stop_website_keepalive(self):
        """Stop the website keepalive thread"""
        self.keepalive_stop_event.set()
    
    def send_message(self, responder: Responder, text: str) -> bool:
        """Send a message to the webhook endpoint"""
        if self.dry_run:
            logger.info(f"[DRY RUN] {responder.name}: {text}")
            return True
        
        if not WEBHOOK_API_KEY:
            logger.error("WEBHOOK_API_KEY not configured - please set environment variable or create .env file")
            return False
        
        current_timestamp = int(time.time())
        message_data = {
            "attachments": [],
            "avatar_url": f"https://i.groupme.com/{random.randint(100, 999)}x{random.randint(100, 999)}.jpeg.{random.randint(10000000, 99999999)}",
            "created_at": current_timestamp,
            "group_id": responder.group_id,
            "id": str(random.randint(100000000000000000, 999999999999999999)),
            "name": responder.name,
            "sender_id": responder.sender_id,
            "sender_type": "user",
            "source_guid": f"{random.randint(10000000, 99999999)}-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}-{random.randint(100000000000, 999999999999)}",
            "system": False,
            "text": text,
            "user_id": responder.user_id
        }
        
        try:
            response = requests.post(
                f"{AZURE_FUNCTION_ENDPOINT}/api/groupme_ingest?code={WEBHOOK_API_KEY}",
                json=message_data,
                headers={
                    "Content-Type": "application/json"
                },
                timeout=10
            )
            response.raise_for_status()
            logger.info(f"✓ {responder.name}: {text}")
            return True
        except Exception as e:
            logger.error(f"Failed to send message from {responder.name}: {e}")
            return False
    
    def simulate_mission(self):
        """Simulate a complete SAR mission"""
        logger.info("Starting mission simulation...")
        
        # Select mission group (real SAR team)
        mission_group_id = self._select_mission_group()
        
        # Authenticate for API access
        if not self._authenticate():
            logger.warning("Authentication failed, keepalive may not work properly")
        
        # Start website keepalive to keep Container App warm
        keepalive_thread = self.start_website_keepalive()
        
        try:
            # Select mission location and generate alert
            location = random.choice(self.snohomish_locations)
            alert_text = self.generate_mission_alert(location)
            
            logger.info(f"Mission: {location.name}")
            logger.info(f"Alert: {alert_text}")
        
            # Create IC responder for the alert
            ic_responder = Responder(
                name="SAR Command",
                user_id="999999999",
                sender_id="999999999",
                experience_level="veteran",
                response_probability=1.0,
                vehicle_preference="Command",
                personality="precise",
                group_id=mission_group_id
            )
        
            # Send initial alert
            if not self.send_message(ic_responder, alert_text):
                logger.error("Failed to send initial alert")
                return
            
            # Wait a bit for the alert to process
            time.sleep(5)
            
            # Select responding responders and assign them to mission group
            all_responders = self.realistic_responders
            responding_responders = []
            for r in all_responders:
                if random.random() < r.response_probability:
                    # Create a copy with the mission group ID
                    mission_responder = Responder(
                        name=r.name,
                        user_id=r.user_id,
                        sender_id=r.sender_id,
                        experience_level=r.experience_level,
                        response_probability=r.response_probability,
                        vehicle_preference=r.vehicle_preference,
                        personality=r.personality,
                        group_id=mission_group_id
                    )
                    responding_responders.append(mission_responder)
            
            # Limit to realistic number (15-25 responders typically)
            max_responders = random.randint(15, 25)
            responding_responders = responding_responders[:max_responders]
            
            logger.info(f"Simulating {len(responding_responders)} responders")
            
            # Phase 1: Initial flood of responses (first 10 minutes)
            self._simulate_initial_responses(responding_responders, location)
            
            # Phase 2: Follow-up questions and updates (next 20 minutes)
            self._simulate_followup_phase(responding_responders)
            
            # Phase 3: Occasional updates and cancellations (next 30 minutes)
            self._simulate_late_phase(responding_responders)
            
            self.update_last_mission_time()
            logger.info("Mission simulation completed")
        
        finally:
            # Stop website keepalive after mission
            logger.info("Stopping website keepalive...")
            self.stop_website_keepalive()
            # Give it a moment to stop gracefully
            keepalive_thread.join(timeout=5)
    
    def _simulate_initial_responses(self, responders: List[Responder], location: MissionLocation):
        """Simulate the initial flood of responses"""
        logger.info("Phase 1: Initial responses")
        
        # Randomize response order
        response_order = list(responders)
        random.shuffle(response_order)
        
        for i, responder in enumerate(response_order):
            # Spread responses over 10 minutes with clustering
            # Simulate exponential distribution manually
            delay = -30 * math.log(random.random()) + random.uniform(0, 600)  # 0-10 minutes
            delay = min(delay, 600)  # Cap at 10 minutes
            
            if delay > 5:  # Don't wait for very short delays in simulation
                time.sleep(min(delay / 60, 10))  # Scale down for simulation
            
            current_msg_time = datetime.fromtimestamp(time.time())
            message = self.generate_natural_message(
                responder, 
                f"Initial response to {location.name} mission", 
                "initial_response",
                current_msg_time
            )
            
            self.send_message(responder, message)
    
    def _simulate_followup_phase(self, responders: List[Responder]):
        """Simulate follow-up questions and clarifications"""
        logger.info("Phase 2: Follow-up messages")
        
        # 30% of responders send follow-up messages
        followup_responders = random.sample(
            responders, 
            max(1, int(len(responders) * 0.3))
        )
        
        for responder in followup_responders:
            delay = random.uniform(60, 1200)  # 1-20 minutes
            time.sleep(min(delay / 60, 5))  # Scale down for simulation
            
            current_msg_time = datetime.fromtimestamp(time.time())
            message = self.generate_natural_message(
                responder,
                "Follow-up question about mission logistics",
                "followup_question",
                current_msg_time
            )
            
            self.send_message(responder, message)
    
    def _simulate_late_phase(self, responders: List[Responder]):
        """Simulate late updates and cancellations"""
        logger.info("Phase 3: Late updates and cancellations")
        
        # 10% cancel, 20% send status updates
        cancellers = random.sample(responders, max(1, int(len(responders) * 0.1)))
        updaters = random.sample(
            [r for r in responders if r not in cancellers], 
            max(1, int(len(responders) * 0.2))
        )
        
        for responder in cancellers:
            delay = random.uniform(300, 1800)  # 5-30 minutes
            time.sleep(min(delay / 60, 3))  # Scale down
            
            current_msg_time = datetime.fromtimestamp(time.time())
            message = self.generate_natural_message(
                responder,
                "Need to cancel response",
                "cancellation",
                current_msg_time
            )
            
            self.send_message(responder, message)
        
        for responder in updaters:
            delay = random.uniform(600, 2400)  # 10-40 minutes
            time.sleep(min(delay / 60, 2))  # Scale down
            
            current_msg_time = datetime.fromtimestamp(time.time())
            message = self.generate_natural_message(
                responder,
                "Status update on response",
                "status_update",
                current_msg_time
            )
            
            self.send_message(responder, message)

def main():
    parser = argparse.ArgumentParser(description="Mission Simulator for Respondr Lite")
    parser.add_argument("--dry-run", action="store_true", 
                       help="Simulate without sending actual messages")
    parser.add_argument("--force-mission", action="store_true",
                       help="Force start a mission regardless of timing")
    
    args = parser.parse_args()
    
    simulator = MissionSimulator(dry_run=args.dry_run)
    
    if args.force_mission or simulator.should_start_mission():
        simulator.simulate_mission()
    else:
        logger.info("No mission needed yet (less than 48 hours since last mission)")

if __name__ == "__main__":
    main()