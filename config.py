# config.py
from typing import List
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Twitter API credentials
    TWITTER_API_KEY = os.getenv('TWITTER_API_KEY')
    TWITTER_API_SECRET = os.getenv('TWITTER_API_SECRET')
    TWITTER_ACCESS_TOKEN = os.getenv('TWITTER_ACCESS_TOKEN')
    TWITTER_ACCESS_TOKEN_SECRET = os.getenv('TWITTER_ACCESS_TOKEN_SECRET')
    
    # OpenAI credentials
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    ASSISTANT_ID = os.getenv('ASSISTANT_ID')
    
    # Twitter API settings
    TWITTER_API_BASE_URL = 'https://api.twitter.com/2'
    
    # Bot settings
    DEFAULT_MENTION_AGE_LIMIT = 180  # minutes
    MAIN_LOOP_DELAY = 250  # seconds
    ERROR_DELAY = 300  # seconds
    MAX_RETRIES = 3
    TWEET_MAX_LENGTH = 280
    
    # New monitoring settings
    ACCOUNTS_TO_MONITOR: List[str] = [
        'wachmc'
    ]
    
    ACCOUNTS_TO_RETWEET: List[str] = [
        'wachmc'
    ]
    
    HASHTAGS_TO_MONITOR: List[str] = [
        '#alephium'
    ]
    
    # Thresholds
    MIN_LIKES_THRESHOLD = 25
    
    # Response settings
    VERIFIED_ONLY = True
    SINGLE_THREAD_RESPONSE = True  # Prevents multiple responses in the same thread