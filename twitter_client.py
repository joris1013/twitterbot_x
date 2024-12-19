import asyncio
import time
import math
import logging
from typing import Dict, List, Optional
from requests_oauthlib import OAuth1Session
from config import Config
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

class TwitterClient:
    def __init__(self):
        self.oauth = OAuth1Session(
            Config.TWITTER_API_KEY,
            client_secret=Config.TWITTER_API_SECRET,
            resource_owner_key=Config.TWITTER_ACCESS_TOKEN,
            resource_owner_secret=Config.TWITTER_ACCESS_TOKEN_SECRET
        )
        self.base_url = Config.TWITTER_API_BASE_URL
        self.user_id = None

    async def _make_request(self, method: str, endpoint: str, params: Dict = None, data: Dict = None, headers: Dict = None, retry_count: int = 0) -> Optional[Dict]:
        
        try:
            url = f"{self.base_url}{endpoint}"
            
            if method.upper() == 'GET':
                response = self.oauth.get(url, params=params, headers=headers)
            elif method.upper() == 'POST':
                response = self.oauth.post(url, json=data, headers=headers)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            if response.status_code == 429:
                reset_time = int(response.headers.get('x-rate-limit-reset', time.time() + 900))
                current_time = time.time()
                sleep_time = max(reset_time - current_time, 60)
                logger.warning(f"Rate limit exceeded. Sleeping for {sleep_time} seconds.")
                await asyncio.sleep(sleep_time)
                return await self._make_request(method, endpoint, params, data, headers)
            
            response.raise_for_status()
            return response.json()
            
        except Exception as e:
            logger.error(f"Error in API request: {str(e)}")
            if retry_count < Config.MAX_RETRIES:
                sleep_time = math.pow(2, retry_count)
                logger.info(f"Retrying after {sleep_time} seconds...")
                await asyncio.sleep(sleep_time)
                return await self._make_request(method, endpoint, params, data, headers, retry_count + 1)
            return None

    async def get_user_id(self) -> Optional[str]:
        """Get the authenticated user's ID."""
        if self.user_id:
            return self.user_id
            
        response = await self._make_request('GET', '/users/me')
        if response and 'data' in response:
            self.user_id = response['data']['id']
            return self.user_id
        return None

    async def get_user_id_by_username(self, username: str) -> Optional[str]:
        """Get a user's ID by their username."""
        try:
            response = await self._make_request('GET', f'/users/by/username/{username}')
            return response.get('data', {}).get('id') if response else None
        except Exception as e:
            logger.error(f"Error getting user ID for username {username}: {str(e)}")
            return None

    async def is_user_verified(self, user_id: str) -> bool:
        """Check if a user is verified."""
        try:
            params = {
                'user.fields': 'verified'
            }
            response = await self._make_request('GET', f'/users/{user_id}', params=params)
            return response.get('data', {}).get('verified', False) if response else False
        except Exception as e:
            logger.error(f"Error checking user verification: {str(e)}")
            return False

    async def get_tweet_metrics(self, tweet_id: str) -> Optional[Dict]:
        """Get engagement metrics for a tweet."""
        try:
            params = {
                'tweet.fields': 'public_metrics,referenced_tweets'
            }
            response = await self._make_request('GET', f'/tweets/{tweet_id}', params=params)
            return response.get('data', {}).get('public_metrics') if response else None
        except Exception as e:
            logger.error(f"Error getting tweet metrics: {str(e)}")
            return None

    async def get_tweet_thread(self, tweet_id: str) -> Optional[str]:
        """Get the conversation ID for a tweet."""
        try:
            params = {
                'tweet.fields': 'conversation_id'
            }
            response = await self._make_request('GET', f'/tweets/{tweet_id}', params=params)
            return response.get('data', {}).get('conversation_id') if response else None
        except Exception as e:
            logger.error(f"Error getting tweet thread: {str(e)}")
            return None
    
    async def _get_latest_mention_id(self) -> Optional[str]:
        """Get the ID of the most recent mention."""
        try:
            params = {
                'max_results': 5,
                'tweet.fields': 'created_at,id'
            }
            
            user_id = await self.get_user_id()
            if not user_id:
                logger.error("Could not get user ID")
                return None
                
            response = await self._make_request('GET', f'/users/{user_id}/mentions', params=params)
            if response and 'data' in response and len(response['data']) > 0:
                return response['data'][0]['id']
            
            logger.info("No previous mentions found")
            return None
            
        except Exception as e:
            logger.error(f"Error getting latest mention ID: {str(e)}")
            return None
    
    async def create_tweet(self, text: str, reply_to: str = None) -> bool:
        try:
            data = {'text': text}
            if reply_to:
                data['reply'] = {'in_reply_to_tweet_id': reply_to}
            
            headers = {'Content-Type': 'application/json'}
            response = await self._make_request('POST', '/tweets', data=data, headers=headers)
            return bool(response and 'data' in response)
            
        except Exception as e:
            logger.error(f"Error creating tweet: {str(e)}")
            return False
        
    async def retweet(self, tweet_id: str) -> bool:
        """Retweet a specific tweet."""
        try:
            user_id = await self.get_user_id()
            if not user_id:
                return False
                
            data = {
                'tweet_id': tweet_id
            }
            
            # Create proper endpoint with tweet_id in the body
            endpoint = f'/users/{user_id}/retweets'
            response = await self._make_request('POST', endpoint, data=data)
            
            if response and 'data' in response:
                logger.info(f"Successfully retweeted tweet {tweet_id}")
                return True
            elif response and 'errors' in response:
                logger.error(f"Failed to retweet {tweet_id}: {response['errors']}")
                return False
                
            return False
        except Exception as e:
            logger.error(f"Error retweeting: {str(e)}")
            return False

    async def unretweet(self, tweet_id: str) -> bool:
        """Remove a retweet."""
        try:
            user_id = await self.get_user_id()
            if not user_id:
                return False
                
            response = await self._make_request('DELETE', f'/users/{user_id}/retweets/{tweet_id}')
            return bool(response and 'data' in response)
        except Exception as e:
            logger.error(f"Error removing retweet: {str(e)}")
            return False
            
    async def get_mentions(self) -> List[Dict]:
        """Get recent mentions of the authenticated user (limited to last 3)."""
        try:
            params = {
                'max_results': 5,  # Changed from 100 to 3
                'tweet.fields': 'author_id,created_at,text,conversation_id',
                'expansions': 'author_id',
                'user.fields': 'username,verified'
            }
            
            user_id = await self.get_user_id()
            if not user_id:
                logger.error("Could not get user ID")
                return []
                
            response = await self._make_request('GET', f'/users/{user_id}/mentions', params=params)
            
            if response and 'data' in response:
                mentions = response['data']
                
                if 'includes' in response and 'users' in response['includes']:
                    user_map = {
                        user['id']: {
                            'username': user['username'],
                            'verified': user.get('verified', False)
                        }
                        for user in response['includes']['users']
                    }
                    
                    for mention in mentions:
                        user_data = user_map.get(mention['author_id'], {})
                        mention['username'] = user_data.get('username')
                        mention['verified'] = user_data.get('verified', False)
                
                logger.info(f"Found {len(mentions)} recent mentions")
                return mentions
            
            return []
                
        except Exception as e:
            logger.error(f"Error getting mentions: {str(e)}")
            return []

    # In twitter_client.py
    async def get_user_tweets(self, username: str) -> List[Dict]:
        """Get recent tweets from a specific user."""
        try:
            user_id = await self.get_user_id_by_username(username)
            if not user_id:
                return []
            
            # Calculate time 2 hours ago in ISO format
            two_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=2))
            
            params = {
                'max_results': 5,
                'tweet.fields': 'public_metrics,created_at,conversation_id',
                'exclude': 'retweets,replies'
            }
            
            response = await self._make_request('GET', f'/users/{user_id}/tweets', params=params)
            
            if not response or 'data' not in response:
                return []
                
            # Filter tweets client-side to ensure they're within 2 hours
            recent_tweets = []
            for tweet in response.get('data', []):
                created_at = datetime.fromisoformat(tweet['created_at'].replace('Z', '+00:00'))
                if created_at > two_hours_ago:
                    recent_tweets.append(tweet)
                else:
                    logger.debug(f"Filtered out tweet from {created_at} as it's older than 2 hours")
                    
            return recent_tweets
        except Exception as e:
            logger.error(f"Error getting user tweets: {str(e)}")
            return []

    async def search_tweets(self, query: str, max_results: int = 50) -> List[Dict]:
        """Search for tweets matching a query."""
        try:
            params = {
                'query': query,
                'max_results': max_results,
                'tweet.fields': 'public_metrics,created_at,author_id,conversation_id',
                'expansions': 'author_id',
                'user.fields': 'username,verified'
            }
            
            response = await self._make_request('GET', '/tweets/search/recent', params=params)
            
            if response and 'data' in response:
                tweets = response['data']
                
                if 'includes' in response and 'users' in response['includes']:
                    user_map = {
                        user['id']: {
                            'username': user['username'],
                            'verified': user.get('verified', False)
                        }
                        for user in response['includes']['users']
                    }
                    
                    for tweet in tweets:
                        user_data = user_map.get(tweet['author_id'], {})
                        tweet['username'] = user_data.get('username')
                        tweet['verified'] = user_data.get('verified', False)
                
                return tweets
            
            return []
            
        except Exception as e:
            logger.error(f"Error searching tweets: {str(e)}")
            return []

    async def like_tweet(self, tweet_id: str) -> bool:
        """Like a specific tweet."""
        try:
            user_id = await self.get_user_id()
            if not user_id:
                return False
                
            data = {
                'tweet_id': tweet_id
            }
            response = await self._make_request('POST', f'/users/{user_id}/likes', data=data)
            return bool(response and 'data' in response)
        except Exception as e:
            logger.error(f"Error liking tweet: {str(e)}")
            return False

    async def unlike_tweet(self, tweet_id: str) -> bool:
        """Remove a like from a tweet."""
        try:
            user_id = await self.get_user_id()
            if not user_id:
                return False
                
            response = await self._make_request('DELETE', f'/users/{user_id}/likes/{tweet_id}')
            return bool(response and 'data' in response)
        except Exception as e:
            logger.error(f"Error unliking tweet: {str(e)}")
            return False