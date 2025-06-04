import asyncio
import logging
from asgiref.sync import sync_to_async
from aiogram.types import Message
from bot.utils.user_autobuy_tasks import user_autobuy_tasks
from bot.commands.autobuy import autobuy_loop
from bot.logger import logger
from bot.config import bot_instance

# Create a fake message class to use when restarting autobuy
class FakeMessage:
    def __init__(self, chat_id, bot=None):
        self.chat_id = chat_id
        self.bot = bot
    
    async def answer(self, text, parse_mode=None):
        """Send a message to the user"""
        # Use the bot instance provided at initialization if available
        # Otherwise fall back to the global bot_instance
        bot = self.bot or bot_instance
        
        if bot:
            await bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode=parse_mode
            )
        else:
            logger.error(f"Cannot send message to {self.chat_id}: bot instance is None")

async def restart_autobuy_for_users(bot=None):
    """Restart autobuy for all users who have it enabled in the database"""
    try:
        # Import User model here to avoid circular imports
        from users.models import User
        
        logger.info("Starting to restart autobuy for users...")
        
        # Get all users with autobuy=True
        autobuy_users = await sync_to_async(list)(User.objects.filter(autobuy=True))
        
        if not autobuy_users:
            logger.info("No users with active autobuy found")
            return
        
        logger.info(f"Found {len(autobuy_users)} users with active autobuy")
        
        # Start autobuy for each user
        for user in autobuy_users:
            # Skip if already running
            if user.telegram_id in user_autobuy_tasks:
                logger.info(f"Autobuy already running for user {user.telegram_id}")
                continue
                
            logger.info(f"Restarting autobuy for user {user.telegram_id}")
            
            # Create a fake message object with the bot instance passed
            fake_message = FakeMessage(chat_id=user.telegram_id, bot=bot)
            
            # Start autobuy task
            task = asyncio.create_task(
                autobuy_loop(fake_message, user.telegram_id)
            )
            
            # Store task reference
            user_autobuy_tasks[user.telegram_id] = task
            
            # Small delay to avoid overloading the system
            await asyncio.sleep(1)
            
        logger.info("Finished restarting autobuy for users")
        
    except Exception as e:
        logger.error(f"Error in restart_autobuy_for_users: {e}", exc_info=True) 