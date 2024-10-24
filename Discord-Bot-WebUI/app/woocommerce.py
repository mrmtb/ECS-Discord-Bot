import requests
import logging
import re
from woocommerce import API
from flask import current_app
import uuid

logger = logging.getLogger(__name__)

def fetch_orders_from_woocommerce(current_season_name, filter_current_season=False, current_season_names=None, max_pages=10):
    """
    Fetch orders from WooCommerce, optionally filtering for current seasons.

    Args:
        current_season_name (str): The name of the current season (e.g., "Fall 2024").
        filter_current_season (bool, optional): Whether to filter orders for current seasons only. Defaults to False.
        current_season_names (list, optional): List of current season names. Required if filter_current_season is True.
        max_pages (int, optional): Maximum number of pages to fetch. Defaults to 10.

    Returns:
        list: A list of filtered order data dictionaries.
    """
    wcapi = API(
        url=current_app.config['WOO_API_URL'],
        consumer_key=current_app.config['WOO_CONSUMER_KEY'],
        consumer_secret=current_app.config['WOO_CONSUMER_SECRET'],
        version="wc/v3"
    )

    orders = []
    page = 1

    # Ensure current_season_name is in "Fall 2024" format
    # If it's in "2024 Fall", rearrange it
    match = re.match(r'(\d{4})\s+(Spring|Fall)', current_season_name, re.IGNORECASE)
    if match:
        year, season = match.groups()
        current_season_formatted = f"{season.capitalize()} {year}"
    else:
        current_season_formatted = current_season_name  # Assume correct format if not matching

    # Define matching patterns
    # For Pub League: "Fall 2024 ECS Pub League"
    season_pub_league_string = f"{current_season_formatted} ECS Pub League"
    # For ECS FC: "ECS FC * Fall 2024" where * is any team name
    ecs_fc_regex_pattern = rf"ECS FC\s+\w+\s+{re.escape(current_season_formatted)}"

    # Compile regex patterns for efficiency
    season_pub_league_regex = re.compile(re.escape(season_pub_league_string), re.IGNORECASE)
    ecs_fc_regex = re.compile(ecs_fc_regex_pattern, re.IGNORECASE)

    # Enhanced logging to reflect accurate matching criteria
    logger.info(f"Looking for orders matching: '{season_pub_league_string}' or 'ECS FC * {current_season_formatted}'")

    while page <= max_pages:
        try:
            params = {
                'status': 'completed',
                'page': page,
                'per_page': 100
            }

            logger.debug(f"Making request to WooCommerce API: {wcapi.url}/orders with params: {params}")
            response = wcapi.get("orders", params=params)
            response.raise_for_status()

            fetched_orders = response.json()
            if not fetched_orders:
                logger.info(f"No more orders found at page {page}. Stopping.")
                break

            # Filter orders based on product name containing specific patterns
            for order in fetched_orders:
                order_id = order.get('id')
                billing = order.get('billing', {})
                for item in order.get('line_items', []):
                    product_name = item.get('name', '')
                    quantity = item.get('quantity', 1)
                    include_order = False

                    # Check for Pub League
                    if season_pub_league_regex.search(product_name):
                        include_order = True
                        logger.debug(f"Order ID {order_id} includes Pub League product: '{product_name}'")
                    
                    # Check for ECS FC
                    elif ecs_fc_regex.search(product_name):
                        include_order = True
                        logger.debug(f"Order ID {order_id} includes ECS FC product: '{product_name}'")
                    
                    # Additional filtering based on current season and division
                    elif filter_current_season and current_season_names:
                        for season in current_season_names:
                            # Ensure season string is in the correct format (e.g., "Fall 2024")
                            if season in product_name and ("Classic Division" in product_name or "Premier Division" in product_name):
                                include_order = True
                                logger.debug(f"Order ID {order_id} includes current season division product: '{product_name}'")
                                break

                    if include_order:
                        orders.append({
                            'order_id': order_id,
                            'product_name': product_name,
                            'billing': billing,
                            'quantity': quantity
                        })
                        logger.debug(f"Included order ID {order_id} with product '{product_name}'")

            logger.info(f"Fetched {len(fetched_orders)} orders from page {page}.")
            page += 1

        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching data from WooCommerce: {e}", exc_info=True)
            break

    logger.info(f"Total orders fetched and included: {len(orders)}")
    return orders

def fetch_order_by_id(order_id):
    wcapi = API(
        url=current_app.config['WOO_API_URL'],
        consumer_key=current_app.config['WOO_CONSUMER_KEY'],
        consumer_secret=current_app.config['WOO_CONSUMER_SECRET'],
        version="wc/v3"
    )

    try:
        logger.info(f"Fetching WooCommerce order with ID: {order_id}")
        response = wcapi.get(f"orders/{order_id}")
        response.raise_for_status()

        order = response.json()

        # Filter based on the product name containing "ECS Pub League", "ECS FC", or other relevant criteria
        for item in order.get('line_items', []):
            product_name = item['name']
            if ("ECS Pub League" in product_name or "ECS FC" in product_name):
                logger.info(f"Order ID {order_id} matches the criteria.")
                return {
                    'order_id': order_id,
                    'product_name': product_name,
                    'billing': order['billing'],
                    'quantity': item.get('quantity', 1)
                }

        logger.warning(f"Order ID {order_id} does not match the criteria.")
        return None

    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching order from WooCommerce: {e}", exc_info=True)
        return None