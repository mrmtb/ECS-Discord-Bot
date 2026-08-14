"""
Discord utility functions extracted from bot_rest_api.py

This module contains Discord-specific utility functions that handle bot initialization,
message parsing, and API interactions.
"""

import asyncio
import json
import logging
import os
from typing import Optional, Tuple

import aiohttp
from aiohttp import ClientError
from discord.ext import commands

# Environment variables
WEBUI_API_URL = os.getenv("WEBUI_API_URL")
from fastapi import HTTPException

from shared_states import get_bot_instance, bot_ready

logger = logging.getLogger(__name__)


async def get_bot():
    """
    Dependency to get the bot instance.
    
    Waits for the bot to be ready and returns the bot instance.
    Used as a FastAPI dependency for endpoints that need bot access.
    
    Returns:
        commands.Bot: The Discord bot instance
        
    Raises:
        HTTPException: If bot is not ready or not initialized properly
    """
    logger.info("get_bot function called. Waiting for bot to be ready...")
    try:
        await asyncio.wait_for(bot_ready.wait(), timeout=30.0)
    except asyncio.TimeoutError:
        logger.error("Timeout waiting for bot to be ready")
        raise HTTPException(status_code=503, detail="Bot is not ready")

    bot = get_bot_instance()
    if bot is None:
        logger.error("Bot instance is None in REST API")
        raise HTTPException(status_code=503, detail="Bot is not initialized properly")

    if not bot.is_ready():
        logger.error("Bot is not in the ready state")
        raise HTTPException(status_code=503, detail="Bot is not in the ready state")

    logger.info(f"Returning bot instance. Bot ID: {bot.user.id if bot.user else 'Unknown'}")
    return bot


def extract_channel_and_message_id(message_id_str):
    """
    Extract channel and message ID from a formatted message ID string.
    
    Args:
        message_id_str (str): Message ID string in format "channel_id-message_id"
        
    Returns:
        tuple: (channel_id, message_id) as strings
        
    Raises:
        ValueError: If message ID format is invalid
    """
    try:
        parts = message_id_str.split('-')
        if len(parts) != 2:
            raise ValueError(f"Invalid message ID format: {message_id_str}")
        return parts[0], parts[1]
    except Exception as e:
        logger.error(f"Error extracting channel and message ID from {message_id_str}: {e}")
        raise ValueError(f"Invalid message ID format: {message_id_str}")


async def get_team_id_for_message(message_id: int, channel_id: int, max_retries=2) -> Tuple[Optional[int], Optional[int]]:
    """
    Get team ID for a given message with improved error handling.

    Makes API requests to retrieve match and team information associated with a Discord message.

    The old defaults -- 5 attempts, 5s sleeps and NO timeout on the request itself
    -- meant the sleeps alone were 20s and a hung webui blocked forever. That
    exceeded the /api/update_embed caller's budget under any circumstances, so
    embed updates were abandoned client-side while this kept retrying against a
    caller that had already left.

    Sizing this is a trade-off between two callers with opposite needs:
      - /api/update_embed (match_routes.py) has a celery caller waiting on it, so
        the total must stay inside that caller's timeout.
      - process_reaction / process_reaction_removal (ECS_Discord_Bot.py) are bare
        create_task with NOBODY waiting. Returning (None, None) there DISCARDS the
        user's RSVP and blacklists the message for 5 minutes, and the only
        reconciliation sweep runs at bot startup. Being impatient here silently
        loses real responses -- far worse than being slow.

    8s per attempt, 2 attempts, 1s sleep => ~17s worst case, which the callers'
    30s+ budgets accommodate. The happy path is a couple of indexed queries, so
    this ceiling is only reached under genuine webui/PgBouncer contention.

    Args:
        message_id (int): Discord message ID
        channel_id (int): Discord channel ID
        max_retries (int, optional): Maximum number of retry attempts. Defaults to 2.

    Returns:
        Tuple[Optional[int], Optional[int]]: (match_id, team_id) or (None, None) if not found
    """
    api_url = f"{WEBUI_API_URL}/get_match_and_team_id_from_message"
    params = {'message_id': str(message_id), 'channel_id': str(channel_id)}
    timeout = aiohttp.ClientTimeout(total=8)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        for attempt in range(max_retries):
            try:
                async with session.get(api_url, params=params) as response:
                    response_text = await response.text()
                    logger.debug(f"Response from API (attempt {attempt + 1}): {response_text}")

                    try:
                        response_data = json.loads(response_text)
                    except json.JSONDecodeError:
                        logger.error(f"Invalid JSON response on attempt {attempt + 1}: {response_text}")
                        await asyncio.sleep(1)
                        continue

                    # Check response format and status
                    status = response_data.get('status')
                    
                    if status == 'success':
                        data = response_data.get('data')
                        if not data:
                            logger.error("Success response without data")
                            await asyncio.sleep(1)
                            continue

                        match_id = data.get('match_id')
                        team_id = data.get('team_id')
                        
                        if match_id is not None and team_id is not None:
                            logger.info(f"Successfully retrieved match_id: {match_id}, team_id: {team_id}")
                            return match_id, team_id
                        else:
                            logger.error("Missing required fields in data")
                    
                    elif status == 'error':
                        error_msg = response_data.get('error', 'Unknown error')
                        logger.error(f"API returned error on attempt {attempt + 1}: {error_msg}")
                        if 'not found' in error_msg.lower():
                            logger.info(f"Message ID {message_id} not found in database - this is likely an old/invalid message")
                            return None, None
                    
                    else:
                        logger.error(f"Unexpected response format on attempt {attempt + 1}")

                    if attempt < max_retries - 1:
                        await asyncio.sleep(1)

            except aiohttp.ClientError as e:
                logger.error(f"Request failed on attempt {attempt + 1}: {str(e)}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Unexpected error on attempt {attempt + 1}: {str(e)}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)

    logger.error(f"Failed to get team ID after {max_retries} attempts")
    return None, None


async def poll_task_result(task_id, max_retries=30, delay=3):
    """
    Polls the task result for a given task_id until it's ready or a maximum number of retries is reached.
    
    Uses exponential backoff with a cap to avoid overwhelming the API.
    
    Args:
        task_id (str): The task ID to poll for results
        max_retries (int, optional): Maximum number of polling attempts. Defaults to 30.
        delay (int, optional): Base delay between attempts in seconds. Defaults to 3.
        
    Returns:
        dict: Task result data or error information
    """
    poll_url = f"{WEBUI_API_URL}/task_status/{task_id}"

    async with aiohttp.ClientSession() as session:
        for attempt in range(max_retries):
            try:
                async with session.get(poll_url) as response:
                    if response.status == 200:
                        result = await response.json()

                        # Log full result for debug purposes
                        logger.debug(f"Polling attempt {attempt + 1}/{max_retries} for task_id {task_id}, received: {result}")

                        task_state = result.get('state', 'PENDING')

                        if task_state == 'SUCCESS':
                            # Ensure `result['result']` exists and is a dictionary
                            task_result = result.get('result')
                            if isinstance(task_result, dict):
                                return task_result
                            else:
                                logger.error(f"Unexpected result format for task_id {task_id}: {task_result}")
                                return {'error': 'Unexpected result format'}

                        elif task_state == 'FAILURE':
                            return {'error': result.get('status', 'Unknown failure')}

                        elif task_state == 'PENDING':
                            logger.info(f"Task {task_id} is still pending, attempt {attempt + 1}/{max_retries}")
                    else:
                        logger.warning(f"Unexpected response status {response.status} while polling task {task_id}, attempt {attempt + 1}/{max_retries}")

                # Exponential backoff delay with a cap of 60 seconds
                await asyncio.sleep(min(delay * (2 ** attempt), 60))

            except ClientError as e:
                logger.error(f"Client error while polling task result (attempt {attempt + 1}/{max_retries}): {str(e)}")
                await asyncio.sleep(delay)

    # Return a specific error if max retries are exhausted
    logger.error(f"Task {task_id} did not complete successfully after {max_retries} retries")
    return {'error': 'Task did not complete successfully'}