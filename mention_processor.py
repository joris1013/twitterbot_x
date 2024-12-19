from datetime import datetime, timezone, timedelta
import logging
from typing import Dict, List, Optional
from twitter_client import TwitterClient
from ai_client import AIClient
from config import Config

logger = logging.getLogger(__name__)

class MentionProcessor:
    def __init__(self, mention_age_limit_minutes: int = Config.DEFAULT_MENTION_AGE_LIMIT):
        self.twitter_client = TwitterClient()
        self.ai_client = AIClient()
        self.mention_age_limit_minutes = mention_age_limit_minutes
        self.user_id = None
        self.last_mention_id = None
        
    async def initialize(self):
        """Initialize the processor by getting the user ID and last mention ID."""
        if not self.user_id:
            self.user_id = await self.twitter_client.get_user_id()
            self.last_mention_id = await self.twitter_client._get_latest_mention_id()
            
    async def get_mentions(self) -> List[Dict]:
        await self.initialize()
        if not self.user_id:
            logger.error("Failed to initialize user ID")
            return []
            
        try:
            mentions = await self.twitter_client.get_mentions()
            
            if mentions:
                filtered_mentions = []
                now = datetime.now(timezone.utc)
                
                for mention in mentions:
                    created_at_str = mention.get('created_at')
                    if created_at_str:
                        created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
                        time_diff = now - created_at
                        if time_diff <= timedelta(minutes=self.mention_age_limit_minutes):
                            filtered_mentions.append(mention)
                        else:
                            logger.info(f"Skipping mention from @{mention.get('username')} older than {self.mention_age_limit_minutes} minutes")
                
                if filtered_mentions:
                    logger.info(f"Found {len(filtered_mentions)} new mentions within the time limit")
                    self.last_mention_id = filtered_mentions[0]['id']
                    return filtered_mentions
            
            return []
                
        except Exception as e:
            logger.error(f"Error getting mentions: {str(e)}")
            return []
            
    async def process_mention(self, mention: Dict) -> None:
        try:
            tweet_id = mention['id']
            # Get username from author data if available, fallback to data structure
            username = (mention.get('author', {}).get('username') or 
                    mention.get('username') or 
                    f"user_{mention.get('author_id', 'unknown')}")
            tweet_text = mention['text']
            
            logger.info(f"Processing mention from @{username}: {tweet_text[:50]}...")
            
            response = await self.ai_client.get_response(username, tweet_text)
            if response:
                if await self.twitter_client.create_tweet(response, tweet_id):
                    logger.info(f"Successfully replied to @{username}")
                else:
                    logger.error(f"Failed to create reply tweet to @{username}")
            else:
                logger.error(f"Failed to generate response for @{username}")
                    
        except Exception as e:
            logger.error(f"Error processing mention: {str(e)}")