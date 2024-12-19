import asyncio
import logging
import re
from typing import Optional
import openai
from config import Config

logger = logging.getLogger(__name__)

class AIClient:
    def __init__(self):
        # Initialize client with authentication
        self.client = openai.AsyncOpenAI(
            api_key=Config.OPENAI_API_KEY
        )
        self.assistant_id = Config.ASSISTANT_ID
        self.poll_interval = 0.5  # Interval to check run status
        
    def clean_response(self, text: str) -> str:
        """Clean up response text by removing reference notations and formatting"""
        if not text:
            return ""
        
        # Remove footnotes like【4:0†Alephium recent development IMPORTANT.txt】
        cleaned = re.sub(r'【\d+:\d+†[^】]+】', '', text)
        
        # Remove bold formatting (**text**)
        cleaned = re.sub(r'\*\*([^*]+)\*\*', r'\1', cleaned)
        
        # Remove italic formatting (*text*)
        cleaned = re.sub(r'\*([^*]+)\*', r'\1', cleaned)
        
        # Remove numbered lists (1., 2., etc)
        cleaned = re.sub(r'\d+\.\s+', '', cleaned)
        
        # Remove bullet points
        cleaned = re.sub(r'[-•]\s+', '', cleaned)
        
        # Remove code formatting (```text```)
        cleaned = re.sub(r'```[^`]*```', '', cleaned)
        
        # Remove inline code formatting (`text`)
        cleaned = re.sub(r'`([^`]+)`', r'\1', cleaned)
        
        # Remove markdown headings (# text)
        cleaned = re.sub(r'#+\s+', '', cleaned)
        
        # Remove markdown links ([text](url))
        cleaned = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', cleaned)
        
        # Remove blockquotes (> text)
        cleaned = re.sub(r'>\s+', '', cleaned)
        
        # Normalize whitespace (including newlines)
        cleaned = re.sub(r'\s+', ' ', cleaned)
        
        return cleaned.strip()
        
    async def get_response(self, username: str, tweet_text: str) -> Optional[str]:
        try:
            # Create a new thread with the initial message
            thread = await self.client.beta.threads.create(
                messages=[
                    {
                        "role": "user",
                        "content": tweet_text
                    }
                ]
            )
            
            # Create a run with the thread
            run = await self.client.beta.threads.runs.create(
                thread_id=thread.id,
                assistant_id=self.assistant_id
            )
            
            # Wait for completion
            run = await self._wait_for_run(thread.id, run.id)
            
            if not run or run.status != 'completed':
                logger.error(f"Run failed with status: {run.status if run else 'None'}")
                return None
            
            # Retrieve the assistant's messages
            messages = await self.client.beta.threads.messages.list(
                thread_id=thread.id,
                order='desc',
                limit=1
            )
            
            # Get the latest message from the assistant
            if messages.data and messages.data[0].role == "assistant":
                # Get the text content from the message
                for content in messages.data[0].content:
                    if content.type == 'text':
                        response = content.text.value
                        # Clean the response
                        cleaned_response = self.clean_response(response)
                        # Truncate if longer than tweet limit
                        if len(cleaned_response) > Config.TWEET_MAX_LENGTH:
                            cleaned_response = cleaned_response[:Config.TWEET_MAX_LENGTH-3] + "..."
                        return cleaned_response
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting AI response: {str(e)}")
            return None
            
    async def _wait_for_run(self, thread_id: str, run_id: str) -> Optional[object]:
        while True:
            try:
                run = await self.client.beta.threads.runs.retrieve(
                    thread_id=thread_id,
                    run_id=run_id
                )
                
                if run.status == 'completed':
                    return run
                elif run.status in ['failed', 'expired', 'cancelled']:
                    logger.error(f"Run failed with status: {run.status}")
                    return None
                elif run.status == 'requires_action':
                    # Handle required actions if needed
                    logger.error("Run requires action - not implemented")
                    return None
                    
                await asyncio.sleep(self.poll_interval)
                
            except Exception as e:
                logger.error(f"Error polling run status: {str(e)}")
                return None