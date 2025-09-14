#!/usr/bin/env python3
"""
Inline Wedding Bot - Uses callback query answers and ephemeral responses

Features:
- Welcome messages in group with buttons
- Responses shown as popup notifications (only visible to clicking user)
- No interference between users
- Clean group chat experience
"""

import os
import requests
import json
import time
import logging
from datetime import datetime, timedelta
import threading
import pickle
import pytz

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class InlineWeddingBot:
    def __init__(self):
        self.bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.group_chat_id = os.getenv('TELEGRAM_GROUP_CHAT_ID')
        
        if not self.bot_token or not self.group_chat_id:
            raise ValueError("Environment variables TELEGRAM_BOT_TOKEN and TELEGRAM_GROUP_CHAT_ID are required")
            
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.last_update_id = 0
        self.member_count = 0  # Track number of members who have joined
        
        # Timezone settings - Singapore Time (UTC+8)
        self.singapore_tz = pytz.timezone('Asia/Singapore')
        
        # Scheduled message settings with persistence
        self.schedule_file = "wedding_schedule.pkl"
        self.scheduled_messages = self.load_schedule()
        self.remove_duplicate_schedules()  # Clean up any duplicates
        self.schedule_initialized = self.check_if_schedule_exists()
        
        # Welcome message with buttons
        self.welcome_keyboard = {
            "inline_keyboard": [
                [
                    {"text": "🏛️ Venue Info", "callback_data": "venue"},
                    {"text": "📅 Schedule", "callback_data": "schedule"}
                ],
                [
                    {"text": "🚇 Transport", "callback_data": "transport"},
                    {"text": "🍽️ Menu", "callback_data": "menu"}
                ],
                [
                    {"text": "📞 Contacts", "callback_data": "contact"},
                    {"text": "ℹ️ Important Note", "callback_data": "help"}
                ]
            ]
        }
        
        logger.info(f"Inline Wedding Bot initialized for group: {self.group_chat_id}")
    
    def send_message(self, chat_id, text, reply_markup=None, reply_to_message_id=None, parse_mode="Markdown"):
        """Send a message with optional inline keyboard."""
        try:
            params = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode
            }
            
            if reply_markup:
                params["reply_markup"] = json.dumps(reply_markup)
            if reply_to_message_id:
                params["reply_to_message_id"] = reply_to_message_id
            
            response = requests.post(f"{self.base_url}/sendMessage", json=params, timeout=30)
            return response.status_code == 200 and response.json().get('ok', False)
        except Exception as e:
            logger.error(f"❌ Error sending message: {e}")
            return False
    
    def answer_callback_query(self, callback_query_id, text, show_alert=True):
        """Answer callback query with popup message visible only to the user."""
        try:
            # Ensure text is not too long (Telegram limit is ~200 characters)
            if len(text) > 200:
                text = text[:197] + "..."
                logger.warning(f"⚠️ Truncated callback text to 200 chars")
            
            params = {
                "callback_query_id": callback_query_id,
                "text": text,
                "show_alert": show_alert  # Shows as popup dialog
            }
            
            response = requests.post(f"{self.base_url}/answerCallbackQuery", json=params, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                if result.get('ok'):
                    logger.info(f"✅ Callback answered successfully")
                    return True
                else:
                    logger.error(f"❌ Callback failed: {result.get('description', 'Unknown error')}")
                    return False
            else:
                logger.error(f"❌ HTTP error {response.status_code}: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error answering callback: {e}")
            return False
    
    def get_updates(self, offset=None, timeout=30):
        """Get updates from Telegram."""
        try:
            params = {"timeout": timeout}
            if offset:
                params["offset"] = offset
            
            response = requests.get(f"{self.base_url}/getUpdates", params=params, timeout=timeout+5)
            
            if response.status_code == 200:
                result = response.json()
                if result['ok']:
                    return result['result']
            return []
        except requests.exceptions.Timeout:
            return []
        except Exception as e:
            logger.error(f"❌ Error getting updates: {e}")
            return []
    
    def get_info_content(self, info_type):
        """Get formatted content for different information types (shortened for popup - max 200 chars)."""
        content = {
            "venue": """🏛️ Park Royal Marina
📍 6 Raffles Blvd, Singapore 039594, Level 5 Atrium Ballroom
🚗 Marina Square parking (coupons available)""",

            "schedule": """📅 27 Sep 2025
🍸 6:30 PM Cocktail
🍽️ 7:15 PM To be Seated
🌙 10:40 PM End
🎉 11:00 PM Afterparty @ OSG Suntec""",

            "transport": """🚇 MRT: Esplanade Station (4 min walk)
🚗 Taxi: Park Royal Marina Hotel Lobby
🅿️ Marina Square parking (coupons available)
📍 Afterparty @OSG Suntec: Postal Code 038983
""",

            "menu": """🍽️ 8-Course Chinese Menu / Halal Menu
🥂 Cocktail: Canapés + free flow drinks
🍾 Drinks: Free flow beer, wine, and soft drinks""",

            "contact": """📞 CONTACTS
👰 Jaz: @jaztww
🤵 Paul: @ywp_88
👧 Ching Yee (OIC): @chingyljy
👦 Samuel (2IC): @butterandink
👦 Zen (Emcee): @zenzcky""",

            "help": """8️⃣8️⃣8️⃣ Bring $2 or $10 notes for lucky draw! The more you bring, the more ballots you have ;) 
"""
        }
        
        return content.get(info_type, "Information not available.")
    
    def handle_callback_query(self, callback_query):
        """Handle inline keyboard button presses with popup responses."""
        query_id = callback_query['id']
        data = callback_query['data']
        user = callback_query['from']
        user_name = user.get('first_name', 'Guest')
        
        logger.info(f"🔘 {user_name} requested: {data}")
        
        if data in ["venue", "schedule", "transport", "menu", "contact", "help"]:
            # Get information content
            content = self.get_info_content(data)
            logger.info(f"📝 Content length for {data}: {len(content)} characters")
            
            # Send as popup notification (only visible to the user who clicked)
            success = self.answer_callback_query(query_id, content, show_alert=True)
            if not success:
                # Fallback: send a simple acknowledgment
                self.answer_callback_query(query_id, f"✅ {data.title()} info sent!", show_alert=False)
        
        else:
            self.answer_callback_query(query_id, "Unknown option", show_alert=False)
    
    def handle_text_command(self, message):
        """Handle text-based commands with replies."""
        text = message.get('text', '').lower().strip()
        chat_id = message['chat']['id']
        message_id = message['message_id']
        user = message['from']
        user_name = user.get('first_name', 'Guest')
        
        # Only respond to commands in the wedding group
        if str(chat_id) != str(self.group_chat_id):
            return
        
        if not text.startswith('/'):
            return
        
        command = text[1:]  # Remove the '/'
        
        if command in ["venue", "schedule", "transport", "menu", "contact", "help"]:
            content = self.get_info_content(command)
            
            # Send response as reply to the user's message
            self.send_message(chat_id, content, reply_to_message_id=message_id)
            logger.info(f"📝 Responded to /{command} from {user_name}")
        
        elif command == "start":
            # Show welcome message with buttons
            welcome_text = f"""Welcome to Paul and Jaz's wedding group! 👋

Here's all the wedding information for **Paul & Jaz's Wedding** on **27 September 2025**.

💡 Click any button below for instant information!

"""
            
            self.send_message(chat_id, welcome_text, self.welcome_keyboard, reply_to_message_id=message_id)
            logger.info(f"📝 Sent welcome message to {user_name}")
    
    def process_new_members(self, message):
        """Track new members and send welcome message every 25 users."""
        if 'new_chat_members' in message:
            new_members = message['new_chat_members']
            
            for member in new_members:
                if member.get('is_bot', False):
                    continue
                
                member_name = member.get('first_name', 'New Member')
                username = member.get('username', '')
                
                # Increment member count
                self.member_count += 1
                
                logger.info(f"👋 New member joined: {member_name} (@{username}) - Total count: {self.member_count}")
                
                # Send welcome message every 25 members
                if self.member_count % 25 == 0:
                    welcome_text = f"""🎉 **Welcome to Paul and Jaz's wedding group!**

We're so excited to celebrate with all of you on **27 September 2025**.

💡 Click any button below for wedding information:

*Use `/start` anytime to see these buttons again!*"""
                    
                    self.send_message(
                        chat_id=self.group_chat_id,
                        text=welcome_text,
                        reply_markup=self.welcome_keyboard
                    )
                    
                    logger.info(f"📢 Sent welcome message for milestone: {self.member_count} members")
    
    def load_schedule(self):
        """Load scheduled messages from file to prevent duplicates on restart."""
        try:
            if os.path.exists(self.schedule_file):
                with open(self.schedule_file, 'rb') as f:
                    schedule = pickle.load(f)
                logger.info(f"📅 Loaded {len(schedule)} scheduled messages from file")
                return schedule
        except Exception as e:
            logger.warning(f"⚠️ Could not load schedule file: {e}")
        
        return []
    
    def save_schedule(self):
        """Save scheduled messages to file."""
        try:
            with open(self.schedule_file, 'wb') as f:
                pickle.dump(self.scheduled_messages, f)
            logger.debug("💾 Schedule saved to file")
        except Exception as e:
            logger.warning(f"⚠️ Could not save schedule: {e}")
    
    def check_if_schedule_exists(self):
        """Check if wedding schedule has already been initialized."""
        if len(self.scheduled_messages) == 0:
            return False
        
        # Check if we have the expected wedding messages (3 messages for our wedding)
        # This prevents duplicates even if schedule file gets corrupted
        wedding_date = self.singapore_tz.localize(datetime(2025, 9, 27, 8, 0))
        expected_dates = [
            wedding_date - timedelta(days=7),  # 1 week before
            wedding_date - timedelta(days=1),  # 1 day before  
            wedding_date                       # wedding day
        ]
        
        # Check if any of our expected dates already exist in schedule
        existing_dates = [msg[0] for msg in self.scheduled_messages]
        for expected_date in expected_dates:
            for existing_date in existing_dates:
                # Compare dates (ignore microseconds and timezone representation differences)
                if (abs((expected_date - existing_date).total_seconds()) < 60):  # Within 1 minute
                    logger.info(f"📅 Found existing wedding schedule, preventing duplicates")
                    return True
        
        return False
    
    def remove_duplicate_schedules(self):
        """Remove any duplicate scheduled messages."""
        if not self.scheduled_messages:
            return
        
        unique_messages = []
        for i, (date1, msg1, buttons1) in enumerate(self.scheduled_messages):
            is_duplicate = False
            for j, (date2, msg2, buttons2) in enumerate(unique_messages):
                # Check if dates are within 1 minute of each other
                if abs((date1 - date2).total_seconds()) < 60:
                    is_duplicate = True
                    logger.info(f"📅 Removing duplicate schedule: {date1}")
                    break
            
            if not is_duplicate:
                unique_messages.append((date1, msg1, buttons1))
        
        if len(unique_messages) != len(self.scheduled_messages):
            self.scheduled_messages = unique_messages
            self.save_schedule()
            logger.info(f"📅 Cleaned up duplicates: {len(unique_messages)} unique messages remain")
    
    def add_scheduled_message(self, target_date, message_text, include_buttons=True):
        """Add a scheduled message to be sent on a specific date."""
        # Check for duplicates before adding
        for existing_date, existing_msg, existing_buttons in self.scheduled_messages:
            if (abs((target_date - existing_date).total_seconds()) < 60):  # Within 1 minute
                logger.info(f"📅 Duplicate message detected, skipping: {target_date}")
                return
        
        self.scheduled_messages.append((target_date, message_text, include_buttons))
        self.save_schedule()  # Save after adding
        logger.info(f"📅 Scheduled message for {target_date}")
    
    def check_scheduled_messages(self):
        """Check and send any scheduled messages that are due."""
        # Get current time in Singapore timezone
        current_time = datetime.now(self.singapore_tz)
        messages_to_remove = []
        
        for i, (target_date, message_text, include_buttons) in enumerate(self.scheduled_messages):
            if current_time >= target_date:
                # Send the scheduled message
                keyboard = self.welcome_keyboard if include_buttons else None
                self.send_message(self.group_chat_id, message_text, keyboard)
                logger.info(f"📤 Sent scheduled message: {message_text[:50]}...")
                messages_to_remove.append(i)
        
        # Remove sent messages from the schedule
        for i in reversed(messages_to_remove):
            self.scheduled_messages.pop(i)
        
        # Save updated schedule if messages were removed
        if messages_to_remove:
            self.save_schedule()
    
    def schedule_wedding_reminders(self):
        """Set up common wedding-related scheduled messages (only if not already done)."""
        if self.schedule_initialized:
            logger.info("📅 Wedding schedule already exists, skipping initialization")
            return
        
        logger.info("📅 Setting up wedding reminder schedule for the first time")
        logger.info(f"🌏 Using Singapore timezone (UTC+8): {self.singapore_tz}")
        
        # Wedding day (September 27, 2025) - All times in Singapore timezone
        wedding_date = self.singapore_tz.localize(datetime(2025, 9, 27, 8, 0))  # 8 AM Singapore time
        
        # 1 week before
        one_week_before = wedding_date - timedelta(days=7)
        week_message = """📅 **One Week Until Paul & Jaz's Wedding!** 🎉

The big day is almost here! Don't forget:
• Confirm your attendance
• Check the venue location
• Plan your outfit
• Arrange transportation

Use /start for all wedding details! 💒"""
        
        # 1 day before  
        one_day_before = wedding_date - timedelta(days=1)
        day_message = """🎊 **Tomorrow is Paul & Jaz's Wedding Day!** 💒

Final reminders:
• Cocktail reception starts at 6:30 PM
• Venue: Park Royal Marina, Level 5 Atrium Ballroom
• Arrive early for photos
• Afterparty at OSG Suntec at 11 PM

See you tomorrow! ✨"""
        
        # Wedding day morning
        wedding_morning = wedding_date
        morning_message = """🎉 **IT'S WEDDING DAY!** 💒✨

Paul & Jaz's special day is here!

📍 Park Royal Marina, Level 5 Atrium Ballroom
⏰ 6:30 PM - Cocktail Reception
🎊 Ready to celebrate? See you there!

Use the buttons below for last-minute details:"""
        
        # Add to schedule
        self.add_scheduled_message(one_week_before, week_message, False)
        self.add_scheduled_message(one_day_before, day_message, False)  
        self.add_scheduled_message(wedding_morning, morning_message, True)
        
        logger.info("📅 Wedding reminder schedule set up successfully")
        logger.info(f"📍 All times are in Singapore timezone (UTC+8)")
        logger.info(f"📅 Schedule: {one_week_before.strftime('%Y-%m-%d %H:%M %Z')}")
        logger.info(f"📅 Schedule: {one_day_before.strftime('%Y-%m-%d %H:%M %Z')}")
        logger.info(f"📅 Schedule: {wedding_morning.strftime('%Y-%m-%d %H:%M %Z')}")
    
    def run_forever(self):
        """Run the inline wedding bot continuously."""
        logger.info("🤖 Starting Inline Wedding Bot...")
        logger.info(f"📱 Monitoring group: {self.group_chat_id}")
        logger.info("💬 Responses shown as private popups")
        
        # Set up wedding reminder schedule
        self.schedule_wedding_reminders()
        
        while True:
            try:
                updates = self.get_updates(offset=self.last_update_id + 1, timeout=30)
                
                for update in updates:
                    self.last_update_id = update['update_id']
                    
                    # Handle callback queries (button presses)
                    if 'callback_query' in update:
                        self.handle_callback_query(update['callback_query'])
                    
                    # Handle regular messages
                    elif 'message' in update:
                        message = update['message']
                        chat_id = message['chat']['id']
                        
                        # Only process messages from the wedding group
                        if str(chat_id) == str(self.group_chat_id):
                            # Handle new members
                            self.process_new_members(message)
                            
                            # Handle text commands
                            if 'text' in message:
                                self.handle_text_command(message)
                
                # Check for scheduled messages every loop
                self.check_scheduled_messages()
                
                time.sleep(1)
                
            except KeyboardInterrupt:
                logger.info("🛑 Bot stopped by user")
                break
            except Exception as e:
                logger.error(f"❌ Bot error: {e}")
                time.sleep(5)


def main():
    """Main function."""
    logger.info("🎉 Starting Inline Wedding Bot for Paul & Jaz")
    
    try:
        bot = InlineWeddingBot()
        bot.run_forever()
    except ValueError as e:
        logger.error(f"❌ Configuration error: {e}")
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")


if __name__ == "__main__":
    main()
