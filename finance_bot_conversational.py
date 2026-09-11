#!/usr/bin/env python3
"""
Finance Group Coordinator Bot - Conversational Edition
Listens to natural conversation, no commands needed.
Understands tasks, questions, and responds naturally.
"""

import os
import json
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
import logging

from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters
from telegram.constants import ParseMode

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# DATABASE
# ============================================================================

DB_FILE = "finance_bot_db.json"

def load_db() -> Dict:
    """Load database from JSON file."""
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            return json.load(f)
    return {
        "tasks": {},
        "logs": [],
        "members": {},
        "conversations": []
    }

def save_db(data: Dict):
    """Save database to JSON file."""
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=2)

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_user_name(user) -> str:
    """Extract user display name from Telegram user object."""
    if user.first_name and user.last_name:
        return f"{user.first_name} {user.last_name}"
    return user.first_name or user.username or f"User {user.id}"

def find_member_by_name(name: str, db: Dict) -> Optional[str]:
    """Find member username by partial name match."""
    name_lower = name.lower()
    for user_id, member in db["members"].items():
        username = member.get("username", "").lower()
        member_name = member.get("name", "").lower()
        if username == name_lower or name_lower in member_name or name_lower in username:
            return username
    return None

def parse_date(text: str) -> Optional[str]:
    """Extract date from text. Returns YYYY-MM-DD format."""
    # Patterns: "Friday", "Sep 20", "2024-09-20", "tomorrow", "in 3 days"
    
    # Try YYYY-MM-DD format
    match = re.search(r'(\d{4})-(\d{2})-(\d{2})', text)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    
    # Try DD/MM or MM/DD format
    match = re.search(r'(\d{1,2})[/-](\d{1,2})', text)
    if match:
        # Assume current year
        month, day = match.groups()
        current_year = datetime.now().year
        return f"{current_year}-{month.zfill(2)}-{day.zfill(2)}"
    
    # Try relative dates
    if "tomorrow" in text.lower():
        return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    
    if "today" in text.lower():
        return datetime.now().strftime("%Y-%m-%d")
    
    # Try "in X days"
    match = re.search(r'in (\d+) days?', text.lower())
    if match:
        days = int(match.group(1))
        return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    
    return None

# ============================================================================
# INTENT DETECTION & NLP
# ============================================================================

def detect_task_assignment(message: str, user_name: str) -> Optional[Tuple[str, str, Optional[str]]]:
    """
    Detect if message contains a task assignment.
    Returns: (assignee, task_description, deadline) or None
    
    Patterns:
    - "Ali, can you do the report?"
    - "@ali finish the analysis by Friday"
    - "Ali needs to complete X by Sep 20"
    - "Someone should do the report"
    """
    
    # Pattern 1: "@name do X [by DATE]"
    pattern1 = r'@(\w+)[,:]?\s+(.+?)(?:\s+by\s+(.+?))?(?:\.|$|!|\?)'
    match = re.search(pattern1, message, re.IGNORECASE)
    if match:
        assignee = match.group(1).lower()
        task = match.group(2).strip()
        deadline = match.group(3).strip() if match.group(3) else None
        
        # Filter out common non-task patterns
        if not any(word in task.lower() for word in ["what", "how", "why", "you think", "you agree"]):
            return (assignee, task, deadline)
    
    # Pattern 2: "Name, can you/should you/need to do X [by DATE]"
    pattern2 = r'([A-Z][a-z]+)[,:]?\s+(?:can you|should you|need to|please|gotta|try to)\s+(.+?)(?:\s+by\s+(.+?))?(?:\.|$|!|\?)'
    match = re.search(pattern2, message)
    if match:
        assignee = match.group(1).lower()
        task = match.group(2).strip()
        deadline = match.group(3).strip() if match.group(3) else None
        return (assignee, task, deadline)
    
    # Pattern 3: "We need X done by DATE" or "Someone should do X"
    if "someone should" in message.lower() or "we need" in message.lower():
        # Extract task but no specific assignee
        pattern3 = r'(?:someone should|we need)\s+(.+?)(?:\s+by\s+(.+?))?(?:\.|$)'
        match = re.search(pattern3, message, re.IGNORECASE)
        if match:
            task = match.group(1).strip()
            deadline = match.group(2).strip() if match.group(2) else None
            return ("team", task, deadline)
    
    return None

def detect_status_question(message: str) -> Optional[str]:
    """
    Detect if message is asking about someone's status/tasks.
    Returns: assignee name or None
    
    Patterns:
    - "What's Ali doing?"
    - "Ali's tasks?"
    - "Where is Fatima at with her work?"
    - "What does Ahmed have?"
    """
    
    # Pattern 1: "What's @name doing/working on?"
    pattern1 = r"(?:what's|what is)\s+@?(\w+)\s+(?:doing|working on|up to|got)" 
    match = re.search(pattern1, message, re.IGNORECASE)
    if match:
        return match.group(1).lower()
    
    # Pattern 2: "@name's tasks/status?"
    pattern2 = r"@?(\w+)'s\s+(?:tasks|status|workload|progress|work)"
    match = re.search(pattern2, message, re.IGNORECASE)
    if match:
        return match.group(1).lower()
    
    # Pattern 3: "Where is @name at?"
    pattern3 = r"where\s+(?:is|are)\s+@?(\w+)\s+(?:at|with)"
    match = re.search(pattern3, message, re.IGNORECASE)
    if match:
        return match.group(1).lower()
    
    return None

def detect_greeting(message: str) -> bool:
    """Detect if message is a greeting/hi to the bot."""
    greetings = ["hi bot", "hello bot", "hey bot", "yo bot", "what's up bot", "@bot"]
    return any(g in message.lower() for g in greetings)

def detect_help_request(message: str) -> bool:
    """Detect if user is asking for help."""
    help_phrases = ["help", "what can you do", "how do i", "commands", "how do you work"]
    return any(h in message.lower() for h in help_phrases)

def detect_decision_log(message: str, user_name: str) -> Optional[str]:
    """
    Detect if message is recording an important decision/agreement.
    Returns: decision text or None
    
    Patterns:
    - "We agreed on X"
    - "Decided that X"
    - "Let's do X"
    - "Everyone agrees: X"
    """
    
    decision_patterns = [
        r"(?:we|everyone)\s+(?:agreed|agree)\s+(?:on|that)\s+(.+?)(?:\.|$)",
        r"(?:decided|decide)\s+(?:that|to)\s+(.+?)(?:\.|$)",
        r"let's\s+(.+?)(?:\.|$)",
        r"all agreed:\s+(.+?)(?:\.|$)"
    ]
    
    for pattern in decision_patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    
    return None

# ============================================================================
# MESSAGE HANDLER
# ============================================================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main message handler - listens to all group messages."""
    
    if not update.message or not update.message.text:
        return
    
    db = load_db()
    user = update.effective_user
    message_text = update.message.text.strip()
    user_name = get_user_name(user)
    
    # Auto-register user
    if str(user.id) not in db["members"]:
        db["members"][str(user.id)] = {
            "username": user.username or user_name.split()[0].lower(),
            "name": user_name,
            "telegram_id": user.id,
            "registered_at": datetime.now().isoformat()
        }
        save_db(db)
    
    # Ignore bot's own messages
    if user.is_bot:
        return
    
    # Don't respond to very short messages or single emoji
    if len(message_text) < 3:
        return
    
    # ====== DETECT INTENTS ======
    
    # 1. Check if it's a greeting to the bot
    if detect_greeting(message_text):
        response = "Hey there! 👋 I'm keeping your finance group organized. Just chat naturally and I'll track tasks, deadlines, and progress. No special commands needed!"
        await update.message.reply_text(response)
        return
    
    # 2. Check if help is requested
    if detect_help_request(message_text):
        help_text = """
✨ I'm here to help your group stay organized!

**Just talk naturally:**
- Tell me to assign tasks: "Ali, can you finish the report by Friday?"
- Ask about someone's work: "What's Fatima working on?"
- Record decisions: "We agreed to meet on Mondays at 2pm"
- I'll track everything and help keep everyone accountable

**I understand:**
📌 Task assignments and deadlines
❓ Questions about who's doing what
📝 Important decisions and agreements
⏰ When things need to be done

Just keep chatting - I'm listening! 👂
"""
        await update.message.reply_text(help_text)
        return
    
    # 3. Check for task assignment
    task_result = detect_task_assignment(message_text, user_name)
    if task_result:
        assignee, task_desc, deadline_str = task_result
        
        # Find actual member
        found_member = find_member_by_name(assignee, db)
        if not found_member:
            response = f"I'm not sure who {assignee} is yet. Did you mean someone else? (They need to say something first)"
            await update.message.reply_text(response)
            return
        
        # Parse deadline
        deadline = None
        if deadline_str:
            deadline = parse_date(f"by {deadline_str}")
        
        # Create task
        task_id = f"task_{len(db['tasks']) + 1}"
        db["tasks"][task_id] = {
            "assignee": found_member,
            "description": task_desc,
            "deadline": deadline,
            "status": "pending",
            "created_by": user_name,
            "created_at": datetime.now().isoformat()
        }
        save_db(db)
        
        # Respond naturally
        deadline_msg = f" by {deadline}" if deadline else ""
        response = f"✅ Got it! {found_member.capitalize()} is on it: {task_desc}{deadline_msg}"
        await update.message.reply_text(response)
        return
    
    # 4. Check for status question
    status_name = detect_status_question(message_text)
    if status_name:
        found_member = find_member_by_name(status_name, db)
        if not found_member:
            response = f"Not sure who you mean by {status_name}. Can you be more specific?"
            await update.message.reply_text(response)
            return
        
        # Find their tasks
        person_tasks = [
            task for task in db["tasks"].values() 
            if task.get("assignee") == found_member and task["status"] == "pending"
        ]
        
        if not person_tasks:
            response = f"@{found_member} is clear! No pending tasks 👍"
            await update.message.reply_text(response)
            return
        
        response = f"@{found_member} has {len(person_tasks)} task(s):\n"
        for task in person_tasks:
            deadline_str = f" (due {task['deadline']})" if task['deadline'] else ""
            response += f"• {task['description']}{deadline_str}\n"
        
        await update.message.reply_text(response)
        return
    
    # 5. Check for decision logging
    decision = detect_decision_log(message_text, user_name)
    if decision:
        db["logs"].append({
            "date": datetime.now().isoformat(),
            "author": user_name,
            "message": decision
        })
        save_db(db)
        
        response = f"📝 Noted: {decision}"
        await update.message.reply_text(response)
        return
    
    # 6. Store conversation for learning (optional)
    db["conversations"].append({
        "timestamp": datetime.now().isoformat(),
        "author": user_name,
        "message": message_text
    })
    
    # Keep only last 1000 messages
    if len(db["conversations"]) > 1000:
        db["conversations"] = db["conversations"][-1000:]
    
    save_db(db)

# ============================================================================
# MAIN APPLICATION
# ============================================================================

def main():
    """Start the bot."""
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    if not TOKEN:
        logger.error("❌ TELEGRAM_BOT_TOKEN environment variable not set!")
        raise ValueError("Set TELEGRAM_BOT_TOKEN in your environment")
    
    application = Application.builder().token(TOKEN).build()
    
    # Add message handler for ALL messages (not just commands)
    application.add_handler(MessageHandler(filters.TEXT, handle_message))
    
    logger.info("🚀 Finance Group Coordinator Bot (Conversational) is running...")
    logger.info("💬 Just chat naturally - no commands needed!")
    
    application.run_polling()

if __name__ == "__main__":
    main()
