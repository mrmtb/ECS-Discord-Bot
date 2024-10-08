from app import db, login_manager
from datetime import datetime
from flask_login import UserMixin, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import event, func, Enum
import enum
import logging
import pyotp

# Get the logger for this module
logger = logging.getLogger(__name__)

# Association table for the many-to-many relationship between User and Role
user_roles = db.Table('user_roles',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id')),
    db.Column('role_id', db.Integer, db.ForeignKey('roles.id'))
)

# Association table for the many-to-many relationship between Role and Permission
role_permissions = db.Table('role_permissions',
    db.Column('role_id', db.Integer, db.ForeignKey('roles.id')),
    db.Column('permission_id', db.Integer, db.ForeignKey('permissions.id'))
)

class League(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    season_id = db.Column(db.Integer, db.ForeignKey('season.id'), nullable=False)
    season = db.relationship('Season', back_populates='leagues')
    teams = db.relationship('Team', back_populates='league', lazy=True)
    players = db.relationship('Player', backref='league_players', lazy=True)
    users = db.relationship('User', back_populates='league')

    def __repr__(self):
        return f'<League {self.name}>'

class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp(), nullable=False)
    updated_at = db.Column(db.DateTime, default=db.func.current_timestamp(), onupdate=db.func.current_timestamp(), nullable=False)
    is_approved = db.Column(db.Boolean, default=False, nullable=False)
    email_notifications = db.Column(db.Boolean, default=True)
    sms_notifications = db.Column(db.Boolean, default=True)
    discord_notifications = db.Column(db.Boolean, default=True)
    profile_visibility = db.Column(db.String(20), default='everyone')
    notifications = db.relationship('Notification', back_populates='user', lazy='dynamic')
    has_completed_onboarding = db.Column(db.Boolean, default=False)
    has_completed_tour = db.Column(db.Boolean, default=False)
    has_skipped_profile_creation = db.Column(db.Boolean, default=False)
    league_id = db.Column(db.Integer, db.ForeignKey('league.id'), nullable=True)
    league = db.relationship('League', back_populates='users')
    is_2fa_enabled = db.Column(db.Boolean, default=False)
    totp_secret = db.Column(db.String(32), nullable=True)

    # Many-to-many relationship between User and Role
    roles = db.relationship('Role', secondary=user_roles, back_populates='users')

    player = db.relationship('Player', back_populates='user', uselist=False)  # Link to Player model

    # Method to generate TOTP secret
    def generate_totp_secret(self):
        import pyotp
        self.totp_secret = pyotp.random_base32()

    # Method to verify the provided 2FA code
    def verify_totp(self, token):
        import pyotp
        totp = pyotp.TOTP(self.totp_secret)
        return totp.verify(token)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def has_role(self, role_name):
        return any(role.name == role_name for role in self.roles)

    def has_permission(self, permission_name):
        return any(permission.name == permission_name for role in self.roles for permission in role.permissions)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

class Role(db.Model):
    __tablename__ = 'roles'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.String(255), nullable=True)

    # Many-to-many relationship between Role and User
    users = db.relationship('User', secondary=user_roles, back_populates='roles')
    # Many-to-many relationship between Role and Permission
    permissions = db.relationship('Permission', secondary=role_permissions, back_populates='roles')

    def __repr__(self):
        return f'<Role {self.name}>'

class Permission(db.Model):
    __tablename__ = 'permissions'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.String(255), nullable=True)
    roles = db.relationship('Role', secondary=role_permissions, back_populates='permissions')

    def __repr__(self):
        return f'<Permission {self.name}>'

class Season(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    league_type = db.Column(db.String(50), nullable=False)
    is_current = db.Column(db.Boolean, default=False, nullable=False)
    leagues = db.relationship('League', back_populates='season', lazy=True)
    player_stats = db.relationship('PlayerSeasonStats', back_populates='season', lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        return f'<Season {self.name} ({self.league_type})>'

class Team(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    league_id = db.Column(db.Integer, db.ForeignKey('league.id'), nullable=False)
    league = db.relationship('League', back_populates='teams')
    players = db.relationship('Player', back_populates='team', lazy=True)
    matches = db.relationship('Schedule', foreign_keys='Schedule.team_id', lazy=True)
    discord_channel_id = db.Column(db.BigInteger, nullable=True)
    discord_coach_role_id = db.Column(db.BigInteger, nullable=True)
    discord_player_role_id = db.Column(db.BigInteger, nullable=True)

    @property
    def recent_form(self):
        # Fetch last 5 matches
        last_five_matches = Match.query.filter(
            (Match.home_team_id == self.id) | (Match.away_team_id == self.id)
        ).order_by(Match.date.desc()).limit(5).all()

        form = []
        for match in last_five_matches:
            if match.home_team_score is not None and match.away_team_score is not None:
                if (match.home_team_id == self.id and match.home_team_score > match.away_team_score) or (
                        match.away_team_id == self.id and match.away_team_score > match.home_team_score):
                    form.append('<span style="color:green;">W</span>')
                elif match.home_team_score == match.away_team_score:
                    form.append('<span style="color:yellow;">D</span>')
                else:
                    form.append('<span style="color:red;">L</span>')
            else:
                form.append('<span style="color:gray;">N/A</span>')

        return ''.join(form)

    @property
    def top_scorer(self):
        # Use PlayerCareerStats to find top scorer
        top_scorer = db.session.query(Player, PlayerCareerStats.goals).join(PlayerCareerStats).filter(
            Player.team_id == self.id
        ).order_by(PlayerCareerStats.goals.desc()).first()
        return f"{top_scorer[0].name} ({top_scorer[1]} goals)" if top_scorer and top_scorer[1] > 0 else "No data"

    @property
    def top_assist(self):
        # Use PlayerCareerStats to find top assist
        top_assist = db.session.query(Player, PlayerCareerStats.assists).join(PlayerCareerStats).filter(
            Player.team_id == self.id
        ).order_by(PlayerCareerStats.assists.desc()).first()
        return f"{top_assist[0].name} ({top_assist[1]} assists)" if top_assist and top_assist[1] > 0 else "No data"

    @property
    def avg_goals_per_match(self):
        # Total goals from PlayerCareerStats
        total_goals = db.session.query(func.sum(PlayerCareerStats.goals)).join(Player).filter(
            Player.team_id == self.id
        ).scalar() or 0
        # Number of matches played
        matches_played = db.session.query(func.count(Match.id)).filter(
            (Match.home_team_id == self.id) | (Match.away_team_id == self.id)
        ).scalar() or 1
        return round(total_goals / matches_played, 2)

    @property
    def popover_content(self):
        return f"<strong>Recent Form:</strong> {self.recent_form}<br>" \
               f"<strong>Top Scorer:</strong> {self.top_scorer}<br>" \
               f"<strong>Top Assist:</strong> {self.top_assist}<br>" \
               f"<strong>Avg Goals/Match:</strong> {self.avg_goals_per_match}"

class PlayerOrderHistory(db.Model):
    __tablename__ = 'player_order_history'

    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)  # Link to Player
    order_id = db.Column(db.String, nullable=False)  # WooCommerce Order ID
    season_id = db.Column(db.Integer, db.ForeignKey('season.id'), nullable=False)  # Link to Season
    league_id = db.Column(db.Integer, db.ForeignKey('league.id'), nullable=False)  # Link to League
    profile_count = db.Column(db.Integer, default=1, nullable=False)  # Number of profiles created for the player in the season
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp(), nullable=False)  # Date the order was created

    # Relationships
    player = db.relationship('Player', backref='order_histories', lazy=True)
    season = db.relationship('Season', backref='order_histories', lazy=True)
    league = db.relationship('League', backref='order_histories', lazy=True)

    def __repr__(self):
        return f'<PlayerOrderHistory {self.player_id} - Order {self.order_id} - Season {self.season_id} - League {self.league_id}>'

class StatChangeLog(db.Model):
    __tablename__ = 'stat_change_logs'

    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)
    stat = db.Column(db.String(50), nullable=False)
    old_value = db.Column(db.Integer, nullable=False)
    new_value = db.Column(db.Integer, nullable=False)
    change_type = db.Column(db.String(10), nullable=False)  # ADD, DELETE, EDIT
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    season_id = db.Column(db.Integer, db.ForeignKey('season.id'), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    player = db.relationship('Player', backref='stat_change_logs')
    user = db.relationship('User', backref='stat_change_logs')
    season = db.relationship('Season', backref='stat_change_logs')

class Player(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20), nullable=True)
    jersey_size = db.Column(db.String(10), nullable=True)
    jersey_number = db.Column(db.Integer, nullable=True)
    is_coach = db.Column(db.Boolean, default=False)
    discord_id = db.Column(db.String(100), unique=True)
    needs_manual_review = db.Column(db.Boolean, default=False)  # New field for manual review
    linked_primary_player_id = db.Column(db.Integer, nullable=True)  # Reference to the primary player
    order_id = db.Column(db.String, nullable=True)
    events = db.relationship('PlayerEvent', back_populates='player', lazy=True, cascade="all, delete-orphan")
    pronouns = db.Column(db.String(50), nullable=True)
    expected_weeks_available = db.Column(db.String(20), nullable=True)
    unavailable_dates = db.Column(db.Text, nullable=True)
    willing_to_referee = db.Column(db.Text, nullable=True)
    favorite_position = db.Column(db.Text, nullable=True)
    other_positions = db.Column(db.Text, nullable=True)
    positions_not_to_play = db.Column(db.Text, nullable=True)
    frequency_play_goal = db.Column(db.Text, nullable=True)
    additional_info = db.Column(db.Text, nullable=True)
    player_notes = db.Column(db.Text, nullable=True)
    team_swap = db.Column(db.String(10), nullable=True) 

    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)
    team = db.relationship('Team', back_populates='players')

    league_id = db.Column(db.Integer, db.ForeignKey('league.id'), nullable=True)
    league = db.relationship('League', back_populates='players')

    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)  # Link to User model
    user = db.relationship('User', back_populates='player')

    availability = db.relationship('Availability', back_populates='player', lazy=True, cascade="all, delete-orphan")

    notes = db.Column(db.Text, nullable=True)  # Admin notes
    is_current_player = db.Column(db.Boolean, default=False)
    profile_picture_url = db.Column(db.String(255), nullable=True)

    # Relationships with stats
    season_stats = db.relationship('PlayerSeasonStats', back_populates='player')
    career_stats = db.relationship('PlayerCareerStats', back_populates='player', uselist=False)

    def __repr__(self):
        return f'<Player {self.name}>'

    # Methods to retrieve season stats
    def get_season_stat(self, season_id, stat):
        season_stat = PlayerSeasonStats.query.filter_by(player_id=self.id, season_id=season_id).first()
        return getattr(season_stat, stat, 0) if season_stat else 0

    def season_goals(self, season_id):
        return self.get_season_stat(season_id, 'goals')

    def season_assists(self, season_id):
        return self.get_season_stat(season_id, 'assists')

    def season_yellow_cards(self, season_id):
        return self.get_season_stat(season_id, 'yellow_cards')

    def season_red_cards(self, season_id):
        return self.get_season_stat(season_id, 'red_cards')

    def update_season_stats(self, season_id, stats_changes, user_id):
        """
        Updates both seasonal and career statistics based on the provided changes.
        """
        if not stats_changes:
            logging.warning(f"No stats changes provided for Player ID {self.id} in Season ID {season_id}.")
            return

        # Fetch or create PlayerSeasonStats for the season
        season_stats = PlayerSeasonStats.query.filter_by(player_id=self.id, season_id=season_id).first()
        if not season_stats:
            season_stats = PlayerSeasonStats(player_id=self.id, season_id=season_id)
            db.session.add(season_stats)

        # Update seasonal stats based on changes
        for stat, increment in stats_changes.items():
            if hasattr(season_stats, stat):
                current_value = getattr(season_stats, stat)
                setattr(season_stats, stat, current_value + increment)
                logging.debug(
                    f"Updated {stat} for Player ID {self.id} in Season ID {season_id}: "
                    f"{current_value} + {increment} = {current_value + increment}"
                )
                # Log the stat change
                self.log_stat_change(stat, current_value, current_value + increment, StatChangeType.EDIT.value, user_id, season_id)
            else:
                logging.warning(
                    f"PlayerSeasonStats has no attribute '{stat}'. Skipping update for Player ID {self.id}."
                )

        # Update career stats based on changes
        self.update_career_stats(stats_changes, user_id)

        # Optionally, log the user performing the update
        logging.info(f"Player ID {self.id} stats updated for Season ID {season_id} by User ID {user_id}.")

        # Removed db.session.commit()

    def update_career_stats(self, stats_changes, user_id):
        """
        Updates career statistics based on the provided changes.
        """
        if not stats_changes:
            logging.warning(f"No stats changes provided for Player ID {self.id} in Career Stats.")
            return

        # Fetch or create PlayerCareerStats
        if not self.career_stats:
            self.career_stats = PlayerCareerStats(player_id=self.id)
            db.session.add(self.career_stats)
            db.session.flush()  # Ensure ID is generated if needed

        # Update career stats based on changes
        for stat, increment in stats_changes.items():
            if hasattr(self.career_stats, stat):
                current_value = getattr(self.career_stats, stat)
                setattr(self.career_stats, stat, current_value + increment)
                logging.debug(
                    f"Updated {stat} for Player ID {self.id} in Career Stats: "
                    f"{current_value} + {increment} = {current_value + increment}"
                )
                # Log the stat change
                self.log_stat_change(stat, current_value, current_value + increment, StatChangeType.EDIT.value, user_id)
            else:
                logging.warning(
                    f"PlayerCareerStats has no attribute '{stat}'. Skipping update for Player ID {self.id}."
                )

        # Optionally, log the user performing the update
        logging.info(f"Player ID {self.id} career stats updated by User ID {user_id}.")

        # Removed db.session.commit()

    def log_stat_change(self, stat, old_value, new_value, change_type, user_id, season_id=None):
        """
        Logs changes to player statistics.

        :param stat: The name of the statistic being changed.
        :param old_value: The previous value of the statistic.
        :param new_value: The new value of the statistic.
        :param change_type: The type of change (ADD, DELETE, EDIT).
        :param user_id: The ID of the user performing the change.
        :param season_id: The ID of the season (optional).
        """
        if change_type not in [ct.value for ct in StatChangeType]:
            logging.warning(f"Invalid change type '{change_type}' for stat change logging.")
            return

        log_entry = StatChangeLog(
            player_id=self.id,
            stat=stat,
            old_value=old_value,
            new_value=new_value,
            change_type=change_type,
            user_id=user_id,
            season_id=season_id
        )
        db.session.add(log_entry)
        db.session.commit()
        logging.info(
            f"Logged stat change for Player ID {self.id}: {stat} {change_type} from {old_value} to {new_value} by User ID {user_id}."
        )

    def get_career_goals(self):
        return self.career_stats.goals if self.career_stats else 0

    def get_career_assists(self):
        return self.career_stats.assists if self.career_stats else 0

    def get_career_yellow_cards(self):
        return self.career_stats.yellow_cards if self.career_stats else 0

    def get_career_red_cards(self):
        return self.career_stats.red_cards if self.career_stats else 0

    def get_all_matches(self):
        """
        Retrieves all matches in which the player's team participated.
        Returns a list of Match objects where the player's team was either the home or away team.
        """
        return Match.query.filter(
            (Match.home_team_id == self.team_id) | (Match.away_team_id == self.team_id)
        ).all()

    def get_all_match_stats(self):
        """
        Retrieves all events (stats) tied to the player, such as goals, assists, yellow cards, etc.
        Returns a list of PlayerEvent objects related to this player.
        """
        return PlayerEvent.query.filter_by(player_id=self.id).all()

class Schedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    week = db.Column(db.String(10), nullable=False)
    date = db.Column(db.Date, nullable=False)
    time = db.Column(db.Time, nullable=False)
    opponent = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    location = db.Column(db.String(100), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    season_id = db.Column(db.Integer, db.ForeignKey('season.id'))  # Add this line

    team = db.relationship('Team', foreign_keys=[team_id])
    opponent_team = db.relationship('Team', foreign_keys=[opponent], post_update=True)
    matches = db.relationship('Match', back_populates='schedule', lazy=True)
    season = db.relationship('Season')

class Match(db.Model):
    __tablename__ = 'matches'
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    time = db.Column(db.Time, nullable=False)
    location = db.Column(db.String(100), nullable=False)
    home_team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    away_team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    home_team_message_id = db.Column(db.String(100), nullable=True)
    away_team_message_id = db.Column(db.String(100), nullable=True)
    home_team_score = db.Column(db.Integer, nullable=True)
    away_team_score = db.Column(db.Integer, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    schedule_id = db.Column(db.Integer, db.ForeignKey('schedule.id'), nullable=False)
    events = db.relationship('PlayerEvent', back_populates='match', lazy=True, cascade="all, delete-orphan")

    home_team = db.relationship('Team', foreign_keys=[home_team_id], backref='home_matches')
    away_team = db.relationship('Team', foreign_keys=[away_team_id], backref='away_matches')
    schedule = db.relationship('Schedule', back_populates='matches')

    availability = db.relationship('Availability', back_populates='match', lazy=True, cascade="all, delete-orphan")

    @property
    def reported(self):
        """
        Determine if the match has been reported based on scores being set.
        Returns True if any score is present (including 0), otherwise False.
        """
        return (
            self.home_team_score is not None and
            self.away_team_score is not None
        )

    def get_opponent_name(self, player):
        """
        Returns the name of the opponent team based on the player's team.
        """
        if player.team_id == self.home_team_id:
            return self.away_team.name
        elif player.team_id == self.away_team_id:
            return self.home_team.name
        else:
            return None  # The player isn't part of either team in this match

class PlayerSeasonStats(db.Model):
    __tablename__ = 'player_season_stats'
    
    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)
    season_id = db.Column(db.Integer, db.ForeignKey('season.id'), nullable=False)
    goals = db.Column(db.Integer, default=0, nullable=False)
    assists = db.Column(db.Integer, default=0, nullable=False)
    yellow_cards = db.Column(db.Integer, default=0, nullable=False)
    red_cards = db.Column(db.Integer, default=0, nullable=False)
    # Additional fields as necessary

    # Use back_populates instead of backref
    player = db.relationship('Player', back_populates='season_stats')
    season = db.relationship('Season', back_populates='player_stats')

class PlayerCareerStats(db.Model):
    __tablename__ = 'player_career_stats'

    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)
    goals = db.Column(db.Integer, default=0, nullable=False)
    assists = db.Column(db.Integer, default=0, nullable=False)
    yellow_cards = db.Column(db.Integer, default=0, nullable=False)
    red_cards = db.Column(db.Integer, default=0, nullable=False)

    player = db.relationship('Player', back_populates='career_stats')

class Standings(db.Model):
    __tablename__ = 'standings'  # Ensure the table name is specified if not following naming conventions

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    season_id = db.Column(db.Integer, db.ForeignKey('season.id'), nullable=False)
    played = db.Column(db.Integer, default=0, nullable=False)
    wins = db.Column(db.Integer, default=0, nullable=False)            # Renamed from 'won'
    draws = db.Column(db.Integer, default=0, nullable=False)           # Renamed from 'drawn'
    losses = db.Column(db.Integer, default=0, nullable=False)          # Renamed from 'lost'
    goals_for = db.Column(db.Integer, default=0, nullable=False)
    goals_against = db.Column(db.Integer, default=0, nullable=False)
    goal_difference = db.Column(db.Integer, default=0, nullable=False)  # Store goal difference in a column
    points = db.Column(db.Integer, default=0, nullable=False)

    # Relationships
    team = db.relationship('Team', backref='standings')
    season = db.relationship('Season', backref='standings')

    # Update goal_difference whenever goals_for or goals_against are changed
    @staticmethod
    def update_goal_difference(mapper, connection, target):
        target.goal_difference = target.goals_for - target.goals_against

# Set up an event listener to automatically update the goal difference
event.listen(Standings, 'before_insert', Standings.update_goal_difference)
event.listen(Standings, 'before_update', Standings.update_goal_difference)

class Availability(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('matches.id'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=True)
    discord_id = db.Column(db.String(100), nullable=False)  # Link to Discord user
    response = db.Column(db.String(10), nullable=False)  # yes, no, maybe

    match = db.relationship('Match', back_populates='availability')
    player = db.relationship('Player', back_populates='availability')

class Notification(db.Model):
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    content = db.Column(db.String(255), nullable=False)
    notification_type = db.Column(db.String(50), nullable=False, default='system')  # 'warning', 'error', 'info', etc.
    icon = db.Column(db.String(50), nullable=True)  # Add this column
    read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship('User', back_populates='notifications')

    def icon_class(self):
        # Use the stored icon if available
        if self.icon:
            return self.icon
        
        # Fallback to default mapping if icon isn't stored
        icon_mapping = {
            'warning': 'ti ti-alert-triangle',
            'error': 'ti ti-alert-circle',
            'info': 'ti ti-info-circle',
            'success': 'ti ti-check-circle',
            'system': 'ti ti-bell'
        }
        return icon_mapping.get(self.notification_type, 'ti-bell')

class Announcement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    position = db.Column(db.Integer, default=0)  # This field should exist

class PlayerEventType(enum.Enum):
    GOAL = 'goal'
    ASSIST = 'assist'
    YELLOW_CARD = 'yellow_card'
    RED_CARD = 'red_card'

class PlayerEvent(db.Model):
    __tablename__ = 'player_event'

    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)
    match_id = db.Column(db.Integer, db.ForeignKey('matches.id'), nullable=False)
    minute = db.Column(db.Integer, nullable=True)
    event_type = db.Column(Enum(PlayerEventType), nullable=False)

    player = db.relationship('Player', back_populates='events')
    match = db.relationship('Match', back_populates='events')

class StatChangeType(enum.Enum):
    ADD = 'add'
    EDIT = 'edit'
    DELETE = 'delete'

class PlayerStatAudit(db.Model):
    __tablename__ = 'player_stat_audit'

    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)
    season_id = db.Column(db.Integer, db.ForeignKey('season.id'), nullable=True)
    stat_type = db.Column(db.String(50), nullable=False)  # e.g., 'goals', 'assists'
    old_value = db.Column(db.Integer, nullable=False)
    new_value = db.Column(db.Integer, nullable=False)
    change_type = db.Column(db.Enum(StatChangeType), nullable=False)
    changed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    player = db.relationship('Player', backref='stat_audits')
    season = db.relationship('Season')
    user = db.relationship('User')