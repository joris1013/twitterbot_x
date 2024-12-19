import asyncio
import logging
import argparse
from mention_processor import MentionProcessor
from config import Config
from datetime import datetime, timezone, timedelta
from collections import deque
import time

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class RateLimiter:
    def __init__(self, requests_per_window: int, window_seconds: int):
        self.requests_per_window = requests_per_window
        self.window_seconds = window_seconds
        self.requests = deque()

    async def acquire(self):
        now = time.time()
        while self.requests and self.requests[0] <= now - self.window_seconds:
            self.requests.popleft()
        
        if len(self.requests) >= self.requests_per_window:
            wait_time = self.requests[0] + self.window_seconds - now
            if wait_time > 0:
                logger.info(f"Rate limit approached, waiting {wait_time:.2f} seconds")
                await asyncio.sleep(wait_time)
        
        self.requests.append(time.time())

def is_tweet_recent(tweet_created_at: str, max_age_minutes: int = 5) -> bool:
    tweet_time = datetime.fromisoformat(tweet_created_at.replace('Z', '+00:00'))
    age = datetime.now(timezone.utc) - tweet_time
    return age <= timedelta(minutes=max_age_minutes)

# In main.py
class TwitterBot:
    def __init__(self, processor: MentionProcessor):
        self.processor = processor
        self.user_tweets_limiter = RateLimiter(10, 900)  # 10 requests per 15 minutes
        self.mentions_limiter = RateLimiter(5, 900)
        self.search_limiter = RateLimiter(5, 900)
        self.retweet_limiter = RateLimiter(3, 900)
        
        self.processed_tweets = set()
        self.last_processed_time = {
            'mentions': 0,
            'accounts': 0,
            'hashtags': 0
        }
        
        # Add minimum intervals between checks
        self.check_intervals = {
            'mentions': 180,  # 3 minutes
            'accounts': 900,  # 15 minutes
            'hashtags': 1800   # 30 minutes
        }

    async def should_process(self, task_type: str) -> bool:
        current_time = time.time()
        last_time = self.last_processed_time[task_type]
        interval = self.check_intervals[task_type]
        
        if current_time - last_time < interval:
            logger.info(f"Skipping {task_type} check - {interval - (current_time - last_time):.0f} seconds until next check")
            return False
        return True

    async def process_accounts(self):
        if time.time() - self.last_processed_time['accounts'] < 900:
            logger.info("Skipping account check - too soon")
            return

        logger.info("Processing accounts...")
        for username in Config.ACCOUNTS_TO_MONITOR + Config.ACCOUNTS_TO_RETWEET:
            try:
                logger.info(f"Checking account: {username}")
                await self.user_tweets_limiter.acquire()
                tweets = await self.processor.twitter_client.get_user_tweets(username)
                
                if not tweets:
                    logger.info(f"No recent tweets found for @{username}")
                    continue
                
                current_time = datetime.now(timezone.utc)
                two_hours_ago = current_time - timedelta(hours=2)
                
                for tweet in tweets:
                    if tweet['id'] in self.processed_tweets:
                        continue
                        
                    created_at = datetime.fromisoformat(tweet['created_at'].replace('Z', '+00:00'))
                    if created_at <= two_hours_ago:
                        logger.info(f"Skipping tweet from @{username} - older than 2 hours")
                        continue
                    
                    # Process all recent tweets from monitored accounts
                    if username in Config.ACCOUNTS_TO_MONITOR:
                        logger.info(f"Processing recent tweet from @{username}")
                        await self.processor.process_mention(tweet)
                    
                    if username in Config.ACCOUNTS_TO_RETWEET:
                        logger.info(f"Retweeting recent tweet from @{username}")
                        await self.retweet_limiter.acquire()
                        success = await self.processor.twitter_client.retweet(tweet['id'])
                        if not success:
                            logger.warning(f"Failed to retweet tweet {tweet['id']}")
                    
                    self.processed_tweets.add(tweet['id'])
                    
                    await asyncio.sleep(15)
                
                await asyncio.sleep(30)
                
            except Exception as e:
                logger.error(f"Error processing account {username}: {str(e)}")
                await asyncio.sleep(30)
        
        self.last_processed_time['accounts'] = time.time()
  
    async def process_mentions(self):
        if time.time() - self.last_processed_time['mentions'] < 180:
            logger.info("Skipping mentions check - too soon")
            return

        await self.mentions_limiter.acquire()
        mentions = await self.processor.get_mentions()
        logger.info(f"Processing {len(mentions)} mentions")
        
        for mention in mentions[:3]:
            if mention['id'] not in self.processed_tweets and is_tweet_recent(mention['created_at']):
                await self.processor.process_mention(mention)
                self.processed_tweets.add(mention['id'])
                await asyncio.sleep(5)
        
        self.last_processed_time['mentions'] = time.time()

# The same file as before, but with this specific change in the process_hashtags() function:

    async def process_hashtags(self):
        if time.time() - self.last_processed_time['hashtags'] < 900:
            logger.info("Skipping hashtag check - too soon")
            return

        logger.info("Processing hashtags...")
        for hashtag in Config.HASHTAGS_TO_MONITOR:
            logger.info(f"Checking hashtag: {hashtag}")
            await self.search_limiter.acquire()
            
            query = f"{hashtag} -is:retweet -is:reply lang:en"
            tweets = await self.processor.twitter_client.search_tweets(query)
            logger.info(f"Found {len(tweets)} tweets with {hashtag}")
            
            processed_count = 0
            for tweet in tweets:
                if tweet['id'] in self.processed_tweets:
                    continue

                # Skip if tweet is from monitored accounts (already processed)
                if any(username.lower() in tweet.get('username', '').lower() 
                    for username in Config.ACCOUNTS_TO_MONITOR):
                    continue

                await self.user_tweets_limiter.acquire()
                metrics = await self.processor.twitter_client.get_tweet_metrics(tweet['id'])
                
                if metrics:
                    like_count = metrics.get('like_count', 0)
                    logger.info(f"Tweet metrics for {tweet.get('username')}: likes={like_count}")

                    # Only check likes threshold
                    if like_count >= Config.MIN_LIKES_THRESHOLD:
                        logger.info(f"Processing tweet with {hashtag} from @{tweet.get('username')} - "
                                f"meets likes threshold ({like_count} likes)")
                        await self.processor.process_mention(tweet)
                        self.processed_tweets.add(tweet['id'])
                        processed_count += 1
                    else:
                        logger.info(f"Skipping tweet from @{tweet.get('username')} - "
                                f"insufficient likes (needs {Config.MIN_LIKES_THRESHOLD})")
                
                if processed_count >= 3:
                    break

                await asyncio.sleep(10)
            
            await asyncio.sleep(10)
        
        self.last_processed_time['hashtags'] = time.time()
        
    def cleanup_processed_tweets(self):
        current_time = time.time()
        self.processed_tweets = {tweet_id for tweet_id in self.processed_tweets 
                               if current_time - float(tweet_id) < 3600}

async def main(mention_age_limit: int = Config.DEFAULT_MENTION_AGE_LIMIT):
    processor = MentionProcessor(mention_age_limit_minutes=mention_age_limit)
    bot = TwitterBot(processor)
    logger.info("Starting Twitter bot...")
    
    while True:
        try:
            # Process mentions
            if await bot.should_process('mentions'):
                logger.info("Checking mentions...")
                await bot.process_mentions()
                bot.last_processed_time['mentions'] = time.time()
            
            # Process accounts
            if await bot.should_process('accounts'):
                logger.info("Checking accounts...")
                await bot.process_accounts()
                bot.last_processed_time['accounts'] = time.time()
            
            # Process hashtags
            if await bot.should_process('hashtags'):
                logger.info("Checking hashtags...")
                await bot.process_hashtags()
                bot.last_processed_time['hashtags'] = time.time()
            
            # Cleanup processed tweets
            bot.cleanup_processed_tweets()
            
            # Wait a shorter time between checks
            logger.info("Sleeping for 60 seconds before next check...")
            await asyncio.sleep(60)
            
        except Exception as e:
            logger.error(f"Error in main loop: {str(e)}")
            await asyncio.sleep(Config.ERROR_DELAY)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--age-limit', type=int, default=Config.DEFAULT_MENTION_AGE_LIMIT, 
                       help='Mention age limit in minutes')
    args = parser.parse_args()
    
    try:
        asyncio.run(main(args.age_limit))
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot crashed: {str(e)}")
        raise