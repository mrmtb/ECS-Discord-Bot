from app import csrf
from flask import Blueprint, render_template, redirect, url_for, flash, send_file, jsonify, request, session, current_app
from flask_login import login_required, current_user
from app.forms import Verify2FAForm
from app.sms_helpers import send_confirmation_sms, verify_sms_confirmation, user_is_blocked_in_textmagic, handle_opt_out, handle_re_subscribe, handle_next_match_request, send_help_message, get_next_match
from app.models import Player, User
from app import db
from io import BytesIO
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from .forms import (
    NotificationSettingsForm,
    PasswordChangeForm,
    Enable2FAForm,
    Disable2FAForm
)
import base64
import requests
import pyotp
import qrcode
import re
import io
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

account_bp = Blueprint('account', __name__, template_folder='templates')

DISCORD_OAUTH2_URL = 'https://discord.com/api/oauth2/authorize'
DISCORD_TOKEN_URL = 'https://discord.com/api/oauth2/token'
DISCORD_API_URL = 'https://discord.com/api/users/@me'

@account_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    notification_form = NotificationSettingsForm(prefix='notification', obj=current_user)
    password_form = PasswordChangeForm(prefix='password')
    enable_2fa_form = Enable2FAForm(prefix='enable2fa')
    disable_2fa_form = Disable2FAForm(prefix='disable2fa')

    return render_template('settings.html', 
                           notification_form=notification_form, 
                           password_form=password_form, 
                           enable_2fa_form=enable_2fa_form,
                           disable_2fa_form=disable_2fa_form,
                           is_2fa_enabled=current_user.is_2fa_enabled)

@account_bp.route('/update_notifications', methods=['POST'])
@login_required
def update_notifications():
    form = NotificationSettingsForm(prefix='notification')
    if form.validate_on_submit():
        current_user.email_notifications = form.email_notifications.data
        current_user.discord_notifications = form.discord_notifications.data
        current_user.profile_visibility = form.profile_visibility.data
        try:
            db.session.commit()
            flash('Notification settings updated successfully.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating notification settings: {str(e)}', 'danger')
    else:
        flash('Error updating notification settings.', 'danger')
    return redirect(url_for('account.settings'))

@account_bp.route('/change_password', methods=['POST'])
@login_required
def change_password():
    form = PasswordChangeForm(prefix='password')
    if form.validate_on_submit():
        if check_password_hash(current_user.password_hash, form.current_password.data):
            new_password_hash = generate_password_hash(form.new_password.data)
            current_user.password_hash = new_password_hash
            try:
                db.session.commit()
                flash('Your password has been updated successfully.', 'success')
            except Exception as e:
                db.session.rollback()
                flash(f'Error updating password: {str(e)}', 'danger')
        else:
            flash('Current password is incorrect.', 'danger')
    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"{field.capitalize()}: {error}", 'danger')
    return redirect(url_for('account.settings'))

@account_bp.route('/update_account_info', methods=['POST'])
@login_required
def update_account_info():
    form = request.form
    current_user.email = form.get('email')
    if current_user.player:
        current_user.player.name = form.get('name')
        current_user.player.phone = form.get('phone')
    try:
        db.session.commit()
        flash('Account information updated successfully', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating account information: {str(e)}', 'danger')
    return redirect(url_for('account.settings'))

@account_bp.route('/initiate-sms-opt-in', methods=['POST'])
@login_required
def initiate_sms_opt_in():
    phone_number = request.json.get('phone_number')
    consent_given = request.json.get('consent_given')
    
    if not phone_number or not consent_given:
        return jsonify(success=False, message="Phone number and consent are required."), 400
    
    if not re.match(r'^\+?1?\d{9,15}$', phone_number):
        return jsonify(success=False, message="Invalid phone number format."), 400
        
    player = Player.query.filter_by(user_id=current_user.id).first()
    if not player:
        player = Player(user_id=current_user.id)
        db.session.add(player)
    
    player.phone = phone_number
    player.is_phone_verified = False
    player.sms_consent_given = True
    player.sms_consent_timestamp = datetime.utcnow()
    player.sms_opt_out_timestamp = None
    
    if user_is_blocked_in_textmagic(phone_number):
        return jsonify(success=False, message="You previously un-subscribed. Please text 'START' to (833) 600 - 7554 re-subscribe to SMS notifications."), 400

    current_user.sms_notifications = True
    
    try:
        db.session.commit()
        success, message = send_confirmation_sms(current_user)
        if success:
            return jsonify(success=True, message="Verification code sent. Please check your phone.")  
        else:
            current_app.logger.error(f'Failed to send SMS to user {current_user.id}. Error: {message}')
            return jsonify(success=False, message="Failed to send verification code. Please try again."), 500
    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, message=f"Error updating SMS settings: {str(e)}"), 500

@account_bp.route('/confirm-sms-opt-in', methods=['POST'])
@login_required  
def confirm_sms_opt_in():
    confirmation_code = request.json.get('confirmation_code')
    
    if not confirmation_code:
        return jsonify(success=False, message="Verification code is required."), 400
    
    if verify_sms_confirmation(current_user, confirmation_code):
        current_user.sms_notifications = True
        current_user.player.is_phone_verified = True    
        try:
            db.session.commit()
            return jsonify(success=True, message="SMS notifications enabled successfully.")
        except Exception as e:
            db.session.rollback()
            return jsonify(success=False, message=f"Error confirming SMS opt-in: {str(e)}"), 500
    else:
        return jsonify(success=False, message="Invalid verification code."), 400

@account_bp.route('/opt-out-sms', methods=['POST'])
@login_required
def opt_out_sms():
    current_user.sms_notifications = False
    current_user.player.sms_opt_out_timestamp = datetime.utcnow()
    try:
        db.session.commit()
        return jsonify(success=True, message="You have successfully opted-out of SMS notifications.")
    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, message=f"Error opting out of SMS notifications: {str(e)}"), 500

@account_bp.route('/sms-opt-in-status', methods=['GET'])
@login_required
def sms_opt_in_status():
    player = Player.query.filter_by(user_id=current_user.id).first()
    return jsonify({
        'is_opted_in': current_user.sms_notifications,
        'is_phone_verified': player.is_phone_verified if player else False,
        'phone_number': player.phone if player else None
    })

@account_bp.route('/resend-sms-confirmation', methods=['POST'])
@login_required
def resend_sms_confirmation():
    success, message = send_confirmation_sms(current_user)
    if success:
        return jsonify(success=True, message="Confirmation code resent successfully!")
    else:
        return jsonify(success=False, message=f"Failed to resend confirmation code: {message}"), 500

@account_bp.route('/sms-verification-status', methods=['GET'])
@login_required
def sms_verification_status():
    is_verified = False
    phone_number = None
    if current_user.player:
        is_verified = current_user.player.is_phone_verified
        phone_number = current_user.player.phone
    return jsonify({'is_verified': is_verified, 'phone_number': phone_number})

@account_bp.route('/enable_2fa', methods=['GET', 'POST'])
@login_required
def enable_2fa():
    if request.method == 'GET':
        if not current_user.totp_secret:
            current_user.totp_secret = pyotp.random_base32()
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                return jsonify(success=False, message=f"Error enabling 2FA: {str(e)}"), 500

        totp = pyotp.TOTP(current_user.totp_secret)
        otp_uri = totp.provisioning_uri(name=current_user.email, issuer_name="ECS Web")

        img = qrcode.make(otp_uri)
        buffered = BytesIO()
        img.save(buffered)
        qr_code = base64.b64encode(buffered.getvalue()).decode()
        
        return jsonify({'qr_code': qr_code, 'secret': current_user.totp_secret})
    
    elif request.method == 'POST':
        data = request.json
        code = data.get('code')
        totp = pyotp.TOTP(current_user.totp_secret)
        
        if totp.verify(code):
            current_user.is_2fa_enabled = True
            try:
                db.session.commit()
                return jsonify({'success': True})
            except Exception as e:
                db.session.rollback()
                return jsonify(success=False, message=f"Error confirming 2FA: {str(e)}"), 500
        else:
            return jsonify({'success': False, 'message': 'Invalid verification code'}), 400

@account_bp.route('/disable_2fa', methods=['POST'])
@login_required
def disable_2fa():
    form = Disable2FAForm(prefix='disable2fa')
    if form.validate_on_submit():
        if current_user.is_2fa_enabled:
            current_user.is_2fa_enabled = False
            current_user.totp_secret = None
            try:
                db.session.commit()
                flash('Two-Factor Authentication has been disabled.', 'success')
            except Exception as e:
                db.session.rollback()
                flash(f"Error disabling 2FA: {str(e)}", 'danger')
        else:
            flash('Two-Factor Authentication is not currently enabled.', 'warning')
    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"{field.capitalize()}: {error}", 'danger')
    return redirect(url_for('account.settings'))

@account_bp.route('/show_2fa_qr', methods=['GET'])
@login_required
def show_2fa_qr():
    try:
        totp_secret = pyotp.random_base32()
        logger.debug(f"TOTP Secret (not saved yet): {totp_secret}")

        totp = pyotp.TOTP(totp_secret)
        otp_uri = totp.provisioning_uri(
            name=current_user.email, 
            issuer_name="ECS Web App"
        )

        logger.debug(f"OTP URI: {otp_uri}")

        img = qrcode.make(otp_uri)
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)

        session['temp_totp_secret'] = totp_secret

        return send_file(buffer, mimetype='image/png')

    except Exception as e:
        logger.error(f"Error generating QR code: {str(e)}")
        return "Error generating QR code", 500

@account_bp.route('/verify_2fa', methods=['POST'])
@login_required
def verify_2fa():
    form = Enable2FAForm(prefix='enable2fa')
    if form.validate_on_submit():
        totp = pyotp.TOTP(current_user.totp_secret)
        if totp.verify(form.totp_token.data):
            current_user.is_2fa_enabled = True
            try:
                db.session.commit()
                return jsonify({"success": True})
            except Exception as e:
                db.session.rollback()
                return jsonify({"success": False, "errors": {"db_error": str(e)}}), 500
        else:
            return jsonify({"success": False, "errors": {"totp_token": "Invalid 2FA token."}}), 400
    return jsonify({"success": False, "errors": form.errors}), 400

@account_bp.route('/link-discord')
@login_required
def link_discord():
    discord_client_id = current_app.config['DISCORD_CLIENT_ID']
    redirect_uri = url_for('account.discord_callback', _external=True)
    scope = 'identify email'
    
    discord_login_url = f"{DISCORD_OAUTH2_URL}?client_id={discord_client_id}&redirect_uri={redirect_uri}&response_type=code&scope={scope}"
    return redirect(discord_login_url)

@account_bp.route('/discord-callback')
@login_required
def discord_callback():
    code = request.args.get('code')
    if not code:
        flash('Discord linking failed. Please try again.', 'danger')
        return redirect(url_for('account.settings'))

    discord_client_id = current_app.config['DISCORD_CLIENT_ID']
    discord_client_secret = current_app.config['DISCORD_CLIENT_SECRET']
    redirect_uri = url_for('account.discord_callback', _external=True)
    
    # Exchange the authorization code for an access token
    data = {
        'client_id': discord_client_id,
        'client_secret': discord_client_secret,
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': redirect_uri,
    }
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    token_response = requests.post(DISCORD_TOKEN_URL, data=data, headers=headers)
    token_json = token_response.json()
    
    if 'access_token' not in token_json:
        flash('Failed to retrieve access token from Discord.', 'danger')
        return redirect(url_for('account.settings'))
    
    access_token = token_json['access_token']
    
    # Fetch user info from Discord
    headers = {'Authorization': f'Bearer {access_token}'}
    user_response = requests.get(DISCORD_API_URL, headers=headers)
    user_json = user_response.json()
    
    discord_email = user_json.get('email')
    discord_id = user_json.get('id')
    
    if not discord_email:
        flash('Unable to access Discord email. Please ensure you have granted email access.', 'danger')
        return redirect(url_for('account.settings'))

    # Check if the Discord email matches the current user's email
    if discord_email.lower() != current_user.email.lower():
        flash('The Discord account email does not match your account email.', 'danger')
        return redirect(url_for('account.settings'))

    # Link the Discord ID to the current user
    if current_user.player:
        current_user.player.discord_id = discord_id
        try:
            db.session.commit()
            flash('Your Discord account has been successfully linked.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f"Error linking Discord account: {str(e)}", 'danger')
    else:
        flash('Unable to link Discord account. Player profile not found.', 'danger')

    return redirect(url_for('account.settings'))

@account_bp.route('/unlink-discord', methods=['POST'])
@login_required
def unlink_discord():
    if current_user.player and current_user.player.discord_id:
        current_user.player.discord_id = None
        try:
            db.session.commit()
            flash('Your Discord account has been unlinked successfully.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f"Error unlinking Discord account: {str(e)}", 'danger')
    else:
        flash('No Discord account is currently linked.', 'info')
    return redirect(url_for('account.settings'))

@csrf.exempt
@account_bp.route('/webhook/incoming-sms', methods=['POST'])
def incoming_sms_webhook():
    logger.info('Received SMS webhook request')
    
    # Process the incoming SMS message from Twilio
    sender_number = request.form.get('From').strip()
    message_text = request.form.get('Body').strip().lower()

    if sender_number.startswith('+1'):
        normalized_sender_number = sender_number[2:]  # Strip the country code for US numbers
    else:
        normalized_sender_number = sender_number

    logger.debug(f'Received message from {sender_number} (normalized to {normalized_sender_number}): "{message_text}"')
    player = Player.query.filter_by(phone=normalized_sender_number).first()

    if player:
        logger.info(f'Player found for phone number: {normalized_sender_number}')
        if message_text == 'end':
            return handle_opt_out(player)
        elif message_text == 'start':
            return handle_re_subscribe(player, normalized_sender_number)
        elif message_text in ['when is my next match', 'next match', 'schedule']:
            return handle_next_match_request(player, normalized_sender_number)
        else:
            logger.warning(f'Unrecognized message from {sender_number}: "{message_text}"')
            return send_help_message(normalized_sender_number)
    else:
        logger.warning(f'No player found for phone number: {normalized_sender_number}')

    return jsonify({'status': 'success'})