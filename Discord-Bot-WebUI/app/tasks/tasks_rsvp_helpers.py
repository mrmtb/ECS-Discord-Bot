# app/tasks/tasks_rsvp_helpers.py

"""
RSVP Helpers Module

This module provides asynchronous helper functions used by RSVP-related tasks.
Functions include updating Discord availability embeds, sending availability messages,
updating user reactions (RSVP) on Discord, notifying Discord of changes, posting messages,
checking the Discord API connection, and handling Discord-related errors.
"""

import logging
import aiohttp
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)


async def update_availability_embed(match_id: int) -> Dict[str, Any]:
    """
    Update the availability embed in Discord for a given match.

    Sends a POST request to the Discord bot API to update the embed for the match.
    Uses a configurable retry mechanism to handle temporary failures.

    Args:
        match_id: The ID of the match.

    Returns:
        A dictionary indicating whether the update was successful, along with a message,
        and, in case of failure, an error message and status code.
    """
    bot_api_url = f"http://discord-bot:5001/api/update_availability_embed/{match_id}"
    max_retries = 3
    retry_delay = 2  # seconds
    
    try:
        for attempt in range(max_retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(bot_api_url, timeout=10 * (attempt + 1)) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            logger.warning(
                                f"Failed to update Discord embed (attempt {attempt+1}/{max_retries})",
                                extra={
                                    'match_id': match_id,
                                    'status': response.status,
                                    'error': error_text
                                }
                            )
                            
                            # If not the last attempt, retry
                            if attempt < max_retries - 1:
                                await asyncio.sleep(retry_delay * (attempt + 1))
                                continue
                            
                            # Last attempt failed, return error
                            return {
                                'success': False,
                                'message': error_text,
                                'status_code': response.status
                            }
                        
                        logger.info(
                            f"Successfully updated Discord embed",
                            extra={'match_id': match_id}
                        )
                        return {
                            'success': True,
                            'message': "Discord embed updated successfully",
                            'timestamp': datetime.utcnow().isoformat()
                        }
            except aiohttp.ClientError as e:
                logger.warning(
                    f"Discord API error updating embed (attempt {attempt+1}/{max_retries})",
                    extra={'match_id': match_id, 'error': str(e)}
                )
                
                # If not the last attempt, retry
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay * (attempt + 1))
                    continue
                
                # Last attempt failed, log and return error
                logger.error(
                    f"Discord API error updating embed after {max_retries} attempts",
                    extra={'match_id': match_id, 'error': str(e)},
                    exc_info=True
                )
                return {
                    'success': False,
                    'message': str(e),
                    'error_type': 'discord_api_error'
                }
                
        # This return should not be reached due to the loop structure,
        # but included as a safety measure
        return {
            'success': False,
            'message': "All retry attempts failed",
            'error_type': 'retry_exhausted'
        }
                
    except Exception as e:
        logger.error(
            f"Unexpected error updating Discord embed",
            extra={'match_id': match_id},
            exc_info=True
        )
        return {
            'success': False,
            'message': str(e),
            'error_type': 'unexpected_error'
        }


async def _send_availability_message_async(message_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Asynchronously send an availability message to Discord.

    'message_data' should include all necessary fields:
    {
        'scheduled_message_id': int,
        'match_id': int,
        'home_channel_id': str,
        'away_channel_id': str,
        'match_date': str,
        'match_time': str,
        'home_team_name': str,
        'away_team_name': str
    }

    Args:
        message_data: Dictionary containing message details.

    Returns:
        A dictionary with the result, including success status, message IDs, and timestamp.
    """
    required_fields = ['scheduled_message_id', 'match_id', 'home_channel_id', 'away_channel_id']
    if not all(f in message_data for f in required_fields):
        logger.error("Missing required fields in message_data", extra={'message_data': message_data})
        return {
            'success': False,
            'message': "Missing required fields in message_data",
            'error_type': 'validation_error'
        }

    # Post message to Discord and get message IDs.
    message_ids = await post_availability_message(message_data)
    if not message_ids:
        return {
            'success': False,
            'message': "Failed to send availability message",
            'error_type': 'discord_send_failed'
        }

    home_message_id, away_message_id = message_ids
    logger.info(
        "Availability message sent successfully",
        extra={
            'scheduled_message_id': message_data['scheduled_message_id'],
            'home_message_id': home_message_id,
            'away_message_id': away_message_id
        }
    )
    
    return {
        'success': True,
        'message': "Availability message sent successfully",
        'home_message_id': home_message_id,
        'away_message_id': away_message_id,
        'sent_at': datetime.utcnow().isoformat()
    }


async def _update_discord_rsvp_async(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Asynchronously update a user's RSVP on Discord.

    The input data should have:
    {
        'match_id': int,
        'discord_id': str,
        'new_response': str,
        'old_response': Optional[str]
    }

    Args:
        data: Dictionary with RSVP update information.

    Returns:
        A dictionary with the update result, including success status and a timestamp.
    """
    required_fields = ['match_id', 'discord_id', 'new_response']
    if not all(key in data for key in required_fields):
        return {
            'success': False,
            'message': "Missing required fields",
            'required_fields': required_fields,
            'error_type': 'validation_error'
        }

    request_data = {
        "match_id": str(data["match_id"]),
        "discord_id": str(data["discord_id"]),
        "new_response": data["new_response"],
        "old_response": data.get("old_response")
    }

    result = await update_user_reaction(request_data)
    return {
        'success': result['success'],
        'message': result['message'],
        'timestamp': datetime.utcnow().isoformat(),
        'sync_status': 'synced' if result['success'] else 'failed'
    }


async def _notify_discord_async(match_id: int) -> Dict[str, Any]:
    """
    Asynchronously notify Discord of RSVP changes for a match.
    This function ensures both Discord embeds and reactions are up-to-date
    with the latest RSVP data from the database.

    Args:
        match_id: The ID of the match.

    Returns:
        A dictionary with the notification result and a timestamp.
    """
    # First update the embed for the match
    embed_result = await update_availability_embed(match_id)
    
    # Log the operation in detail
    notification_time = datetime.utcnow().isoformat()
    
    if not embed_result.get('success', False):
        logger.error(f"Failed to update Discord embed for match {match_id}: {embed_result.get('message', 'Unknown error')}")
        return {
            'success': False,
            'message': f"Failed to update Discord embed: {embed_result.get('message', 'Unknown error')}",
            'notification_time': notification_time
        }
    
    logger.info(f"Successfully notified Discord of RSVP changes for match {match_id}")
    return {
        'success': True,
        'message': "Discord notified successfully of RSVP changes",
        'notification_time': notification_time,
        'details': embed_result.get('message', 'Discord embed updated successfully')
    }


async def post_availability_message(message_data: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """
    Post an availability message to Discord and return message IDs.

    Args:
        message_data: Dictionary containing the message details.

    Returns:
        A tuple (home_message_id, away_message_id) if successful, or None otherwise.
    """
    bot_api_url = "http://discord-bot:5001/api/post_availability"
    
    # Retry parameters
    max_retries = 3
    initial_backoff = 5  # seconds
    
    for attempt in range(max_retries):
        try:
            async with aiohttp.ClientSession() as session:
                logger.info(
                    f"Sending availability message (attempt {attempt+1}/{max_retries})",
                    extra={'match_id': message_data.get('match_id')}
                )
                
                timeout = 30 * (attempt + 1)  # Increase timeout for each retry
                async with session.post(bot_api_url, json=message_data, timeout=timeout) as response:
                    if response.status == 429:  # Rate limited
                        error_text = await response.text()
                        retry_after = response.headers.get('Retry-After', initial_backoff * (2 ** attempt))
                        try:
                            retry_after = int(retry_after)
                        except (ValueError, TypeError):
                            retry_after = initial_backoff * (2 ** attempt)
                        
                        logger.warning(
                            f"Discord rate limit hit, retrying after {retry_after}s",
                            extra={
                                'status': response.status,
                                'retry_after': retry_after,
                                'attempt': attempt + 1,
                                'match_id': message_data.get('match_id')
                            }
                        )
                        await asyncio.sleep(retry_after)
                        continue
                        
                    elif response.status != 200:
                        error_text = await response.text()
                        if attempt < max_retries - 1:
                            backoff = initial_backoff * (2 ** attempt)
                            logger.warning(
                                f"Failed to post availability message, retrying in {backoff}s",
                                extra={
                                    'status': response.status,
                                    'error': error_text,
                                    'attempt': attempt + 1,
                                    'match_id': message_data.get('match_id')
                                }
                            )
                            await asyncio.sleep(backoff)
                            continue
                        else:
                            logger.error(
                                "Failed to post availability message after all retries",
                                extra={
                                    'status': response.status,
                                    'error': error_text,
                                    'match_id': message_data.get('match_id')
                                }
                            )
                            return None
                    
                    result = await response.json()
                    
                    logger.info(
                        "Posted availability message successfully",
                        extra={
                            'match_id': message_data.get('match_id'),
                            'message_ids': {
                                'home': result.get('home_message_id'),
                                'away': result.get('away_message_id')
                            }
                        }
                    )
                    
                    return result.get('home_message_id'), result.get('away_message_id')
                    
        except aiohttp.ClientError as e:
            if attempt < max_retries - 1:
                backoff = initial_backoff * (2 ** attempt)
                logger.warning(
                    f"Discord API error, retrying in {backoff}s",
                    extra={
                        'error': str(e),
                        'attempt': attempt + 1,
                        'match_id': message_data.get('match_id')
                    }
                )
                await asyncio.sleep(backoff)
            else:
                logger.error(
                    "Discord API error after all retries",
                    extra={'match_id': message_data.get('match_id')},
                    exc_info=True
                )
                return None
    
    # If we get here, all retries failed
    logger.error(
        f"Failed to post availability message after {max_retries} attempts",
        extra={'match_id': message_data.get('match_id')}
    )
    return None


async def update_user_reaction(request_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Update a user's reaction (RSVP) on Discord.
    
    This function checks if the requested update is actually needed before making
    the Discord API call, to avoid unnecessary reaction updates that might cause race conditions.

    Args:
        request_data: Dictionary containing 'match_id', 'discord_id', 'new_response', and optionally 'old_response'.

    Returns:
        A dictionary with the result of the update operation, including success status, message, and duration.
    """
    bot_api_url = "http://discord-bot:5001/api/update_user_reaction"
    
    required_fields = ['match_id', 'discord_id', 'new_response']
    if not all(key in request_data for key in required_fields):
        return {
            'success': False,
            'message': "Missing required fields",
            'required_fields': required_fields,
            'error_type': 'validation_error'
        }

    # Ensure discord_id is a string
    request_data['discord_id'] = str(request_data['discord_id'])
    
    # First, check with Flask API if this update is needed
    # This helps avoid race conditions where we might be trying to update to a state that's already correct
    try:
        check_api_url = f"http://webui:5000/api/get_match_rsvps/{request_data['match_id']}?include_discord_ids=true"
        async with aiohttp.ClientSession() as check_session:
            async with check_session.get(check_api_url) as response:
                if response.status == 200:
                    rsvp_data = await response.json()
                    
                    # Check each list to find the user's current status
                    current_status = None
                    for status in ['yes', 'no', 'maybe']:
                        for player in rsvp_data.get(status, []):
                            if player.get('discord_id') == request_data['discord_id']:
                                current_status = status
                                break
                        if current_status:
                            break
                    
                    # If the user's current status matches what we're trying to update it to,
                    # we can skip the update to avoid potential race conditions
                    if current_status == request_data['new_response']:
                        logger.info(f"User {request_data['discord_id']} already has response {current_status} in database. Skipping reaction update.")
                        return {
                            'success': True,
                            'message': "User already has the correct response in database. No update needed.",
                            'timestamp': datetime.utcnow().isoformat(),
                            'sync_status': 'synced'
                        }
    except Exception as e:
        logger.warning(f"Could not verify current RSVP status: {str(e)}. Proceeding with update.")
    
    # Max retries and backoff
    max_retries = 3
    retry_delay = 2  # seconds
    
    for attempt in range(max_retries):
        start_time = datetime.utcnow()
        try:
            async with aiohttp.ClientSession() as session:
                # Increase timeout for each retry
                timeout = 30 * (attempt + 1)
                async with session.post(bot_api_url, json=request_data, timeout=timeout) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.warning(
                            f"Failed to update Discord RSVP (attempt {attempt+1}/{max_retries})",
                            extra={
                                'status': response.status,
                                'error': error_text,
                                'match_id': request_data.get('match_id'),
                                'discord_id': request_data.get('discord_id')
                            }
                        )
                        
                        # If not the last attempt, retry
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay * (attempt + 1))
                            continue
                            
                        # Last attempt failed
                        return {
                            'success': False,
                            'message': f"Failed to update Discord RSVP: {error_text}",
                            'error_type': 'discord_api_error',
                            'status_code': response.status
                        }
                        
                    duration = (datetime.utcnow() - start_time).total_seconds()
                    logger.info(
                        "Discord RSVP update successful",
                        extra={
                            'match_id': request_data.get('match_id'),
                            'discord_id': request_data.get('discord_id'),
                            'duration': duration,
                            'new_response': request_data.get('new_response')
                        }
                    )
                    return {
                        'success': True,
                        'message': "Discord RSVP updated successfully",
                        'timestamp': datetime.utcnow().isoformat(),
                        'duration': duration
                    }
        except aiohttp.ClientError as e:
            error_msg = f"Discord API error: {str(e)}"
            logger.error(
                "Discord API error updating RSVP",
                extra={
                    'match_id': request_data.get('match_id'),
                    'discord_id': request_data.get('discord_id'),
                    'error': str(e)
                },
                exc_info=True
            )
            
            # If not the last attempt, retry
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay * (attempt + 1))
                continue
            
            # Last attempt failed
            return {
                'success': False,
                'message': error_msg,
                'error_type': 'discord_api_error'
            }
        except Exception as e:
            error_msg = f"Error updating Discord RSVP: {str(e)}"
            logger.error(
                "Unexpected error updating RSVP",
                extra={
                    'match_id': request_data.get('match_id'),
                    'discord_id': request_data.get('discord_id')
                },
                exc_info=True
            )
            
            # If not the last attempt, retry
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay * (attempt + 1))
                continue
            
            # Last attempt failed
            return {
                'success': False,
                'message': error_msg,
                'error_type': 'unexpected_error'
            }
    
    # This should not be reached due to the loop structure
    return {
        'success': False,
        'message': "All retry attempts failed",
        'error_type': 'retry_exhausted'
    }


async def check_discord_connection() -> Dict[str, Any]:
    """
    Check the health of the Discord bot API connection.

    Returns:
        A dictionary indicating whether the connection is healthy along with a timestamp.
    """
    bot_api_url = "http://discord-bot:5001/api/health"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(bot_api_url, timeout=5) as response:
                if response.status != 200:
                    return {
                        'success': False,
                        'message': "Discord bot API health check failed",
                        'status_code': response.status
                    }
                return {
                    'success': True,
                    'message': "Discord bot API connection healthy",
                    'timestamp': datetime.utcnow().isoformat()
                }
    except Exception as e:
        return {
            'success': False,
            'message': f"Discord bot API connection error: {str(e)}",
            'error_type': 'connection_error'
        }


def handle_discord_error(e: Exception, context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle Discord-related errors by logging detailed information.

    Args:
        e: The exception that was raised.
        context: A dictionary containing additional context about the error.

    Returns:
        A dictionary containing error details, including the error type and a timestamp.
    """
    error_msg = str(e)
    error_type = 'discord_api_error' if isinstance(e, aiohttp.ClientError) else 'unexpected_error'
    
    logger.error(
        f"Discord operation error: {error_msg}",
        extra={
            'error_type': error_type,
            'context': context
        },
        exc_info=True
    )
    
    return {
        'success': False,
        'message': error_msg,
        'error_type': error_type,
        'context': context,
        'timestamp': datetime.utcnow().isoformat()
    }