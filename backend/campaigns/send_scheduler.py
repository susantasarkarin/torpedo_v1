"""
Send Scheduler - Timezone-Aware Email Scheduling Service

Handles timezone detection from lead location data and validates
optimal send windows based on recipient local time.

Dependencies: timezonefinder, pytz
Installation: pip install timezonefinder pytz

Author: Agent 6
Date: 2026-01-28
"""

from datetime import datetime
import pytz
from typing import Optional, List, Tuple, Dict
from timezonefinder import TimezoneFinder
import logging

logger = logging.getLogger(__name__)


class SendScheduler:
    """Timezone-aware email send scheduling service."""
    
    # Common US state to timezone mappings
    US_STATE_TIMEZONES = {
        'AL': 'America/Chicago', 'AK': 'America/Anchorage', 'AZ': 'America/Phoenix',
        'AR': 'America/Chicago', 'CA': 'America/Los_Angeles', 'CO': 'America/Denver',
        'CT': 'America/New_York', 'DE': 'America/New_York', 'FL': 'America/New_York',
        'GA': 'America/New_York', 'HI': 'Pacific/Honolulu', 'ID': 'America/Denver',
        'IL': 'America/Chicago', 'IN': 'America/Indiana/Indianapolis', 'IA': 'America/Chicago',
        'KS': 'America/Chicago', 'KY': 'America/Kentucky/Louisville', 'LA': 'America/Chicago',
        'ME': 'America/New_York', 'MD': 'America/New_York', 'MA': 'America/New_York',
        'MI': 'America/Detroit', 'MN': 'America/Chicago', 'MS': 'America/Chicago',
        'MO': 'America/Chicago', 'MT': 'America/Denver', 'NE': 'America/Chicago',
        'NV': 'America/Los_Angeles', 'NH': 'America/New_York', 'NJ': 'America/New_York',
        'NM': 'America/Denver', 'NY': 'America/New_York', 'NC': 'America/New_York',
        'ND': 'America/Chicago', 'OH': 'America/New_York', 'OK': 'America/Chicago',
        'OR': 'America/Los_Angeles', 'PA': 'America/New_York', 'RI': 'America/New_York',
        'SC': 'America/New_York', 'SD': 'America/Chicago', 'TN': 'America/Chicago',
        'TX': 'America/Chicago', 'UT': 'America/Denver', 'VT': 'America/New_York',
        'VA': 'America/New_York', 'WA': 'America/Los_Angeles', 'WV': 'America/New_York',
        'WI': 'America/Chicago', 'WY': 'America/Denver'
    }
    
    # Major city to timezone mappings
    CITY_TIMEZONES = {
        'new york': 'America/New_York', 'los angeles': 'America/Los_Angeles',
        'chicago': 'America/Chicago', 'houston': 'America/Chicago',
        'phoenix': 'America/Phoenix', 'philadelphia': 'America/New_York',
        'san antonio': 'America/Chicago', 'san diego': 'America/Los_Angeles',
        'dallas': 'America/Chicago', 'san jose': 'America/Los_Angeles',
        'austin': 'America/Chicago', 'jacksonville': 'America/New_York',
        'san francisco': 'America/Los_Angeles', 'columbus': 'America/New_York',
        'fort worth': 'America/Chicago', 'indianapolis': 'America/Indiana/Indianapolis',
        'charlotte': 'America/New_York', 'seattle': 'America/Los_Angeles',
        'denver': 'America/Denver', 'washington': 'America/New_York',
        'boston': 'America/New_York', 'nashville': 'America/Chicago',
        'detroit': 'America/Detroit', 'portland': 'America/Los_Angeles',
        'las vegas': 'America/Los_Angeles', 'miami': 'America/New_York',
        'atlanta': 'America/New_York', 'london': 'Europe/London',
        'paris': 'Europe/Paris', 'tokyo': 'Asia/Tokyo',
        'sydney': 'Australia/Sydney', 'toronto': 'America/Toronto',
        'vancouver': 'America/Vancouver', 'mumbai': 'Asia/Kolkata',
        'dubai': 'Asia/Dubai', 'singapore': 'Asia/Singapore'
    }
    
    # Country to default timezone mappings
    COUNTRY_TIMEZONES = {
        'US': 'America/New_York', 'USA': 'America/New_York',
        'United States': 'America/New_York',
        'UK': 'Europe/London', 'United Kingdom': 'Europe/London',
        'CA': 'America/Toronto', 'Canada': 'America/Toronto',
        'AU': 'Australia/Sydney', 'Australia': 'Australia/Sydney',
        'DE': 'Europe/Berlin', 'Germany': 'Europe/Berlin',
        'FR': 'Europe/Paris', 'France': 'Europe/Paris',
        'JP': 'Asia/Tokyo', 'Japan': 'Asia/Tokyo',
        'IN': 'Asia/Kolkata', 'India': 'Asia/Kolkata',
        'SG': 'Asia/Singapore', 'Singapore': 'Asia/Singapore',
        'AE': 'Asia/Dubai', 'UAE': 'Asia/Dubai'
    }
    
    # Default send windows (hour ranges in local time)
    DEFAULT_SEND_WINDOWS = [
        (9, 11),   # 9am - 11am
        (14, 16)   # 2pm - 4pm
    ]
    
    def __init__(self):
        """Initialize the send scheduler with timezone finder."""
        self.tf = TimezoneFinder()
        logger.info("SendScheduler initialized")
    
    def detect_timezone(self, city: str = None, state: str = None, 
                       country: str = None, latitude: float = None, 
                       longitude: float = None) -> Optional[str]:
        """
        Detect timezone from location data.
        
        Tries multiple strategies in order:
        1. Latitude/longitude (most accurate)
        2. City name lookup
        3. US state code
        4. Country default
        
        Args:
            city: City name
            state: State code (e.g., 'CA', 'NY')
            country: Country name or code
            latitude: Geographic latitude
            longitude: Geographic longitude
            
        Returns:
            IANA timezone string (e.g., 'America/New_York') or None
        """
        try:
            # Strategy 1: Use coordinates if available (most accurate)
            if latitude is not None and longitude is not None:
                tz = self.tf.timezone_at(lat=latitude, lng=longitude)
                if tz:
                    logger.debug(f"Timezone detected from coordinates: {tz}")
                    return tz
            
            # Strategy 2: City lookup
            if city:
                city_lower = city.lower().strip()
                if city_lower in self.CITY_TIMEZONES:
                    tz = self.CITY_TIMEZONES[city_lower]
                    logger.debug(f"Timezone detected from city '{city}': {tz}")
                    return tz
            
            # Strategy 3: US State lookup
            if state:
                state_upper = state.upper().strip()
                if state_upper in self.US_STATE_TIMEZONES:
                    tz = self.US_STATE_TIMEZONES[state_upper]
                    logger.debug(f"Timezone detected from state '{state}': {tz}")
                    return tz
            
            # Strategy 4: Country default
            if country:
                country_key = country.strip()
                if country_key in self.COUNTRY_TIMEZONES:
                    tz = self.COUNTRY_TIMEZONES[country_key]
                    logger.debug(f"Timezone detected from country '{country}': {tz}")
                    return tz
            
            # Fallback: US Eastern Time
            logger.warning(f"Could not detect timezone for city={city}, state={state}, "
                         f"country={country}. Using default: America/New_York")
            return 'America/New_York'
            
        except Exception as e:
            logger.error(f"Error detecting timezone: {e}")
            return None
    
    def get_recipient_local_time(self, recipient: Dict, 
                                 reference_time: datetime = None) -> Optional[datetime]:
        """
        Calculate the recipient's local time.
        
        Args:
            recipient: Dictionary containing location data
                      Expected keys: city, state, country, latitude, longitude
            reference_time: Reference datetime (default: now in UTC)
            
        Returns:
            Datetime in recipient's local timezone or None if timezone cannot be determined
        """
        try:
            # Extract location data
            city = recipient.get('city')
            state = recipient.get('state')
            country = recipient.get('country')
            lat = recipient.get('latitude')
            lng = recipient.get('longitude')
            
            # Detect timezone
            tz_name = self.detect_timezone(
                city=city,
                state=state,
                country=country,
                latitude=lat,
                longitude=lng
            )
            
            if not tz_name:
                return None
            
            # Get timezone object
            tz = pytz.timezone(tz_name)
            
            # Use current time if no reference provided
            if reference_time is None:
                reference_time = datetime.utcnow()
            
            # Ensure reference time is timezone-aware (UTC)
            if reference_time.tzinfo is None:
                reference_time = pytz.utc.localize(reference_time)
            
            # Convert to recipient's local time
            local_time = reference_time.astimezone(tz)
            logger.debug(f"Recipient local time: {local_time} (timezone: {tz_name})")
            
            return local_time
            
        except Exception as e:
            logger.error(f"Error calculating recipient local time: {e}")
            return None
    
    def is_within_send_window(self, local_time: datetime, 
                              windows: List[Tuple[int, int]] = None) -> bool:
        """
        Check if the given local time falls within acceptable send windows.
        
        Args:
            local_time: Datetime in recipient's local timezone
            windows: List of (start_hour, end_hour) tuples (default: 9-11am, 2-4pm)
            
        Returns:
            True if within any send window, False otherwise
        """
        if windows is None:
            windows = self.DEFAULT_SEND_WINDOWS
        
        try:
            hour = local_time.hour
            
            for start_hour, end_hour in windows:
                if start_hour <= hour < end_hour:
                    logger.debug(f"Time {hour}:00 is within send window {start_hour}-{end_hour}")
                    return True
            
            logger.debug(f"Time {hour}:00 is outside all send windows")
            return False
            
        except Exception as e:
            logger.error(f"Error checking send window: {e}")
            return False
    
    def can_send_now(self, recipient: Dict, 
                     windows: List[Tuple[int, int]] = None) -> Tuple[bool, Optional[str]]:
        """
        Determine if an email can be sent to the recipient right now.
        
        Args:
            recipient: Dictionary containing location data
            windows: Optional custom send windows
            
        Returns:
            Tuple of (can_send: bool, reason: str)
        """
        try:
            # Get recipient's local time
            local_time = self.get_recipient_local_time(recipient)
            
            if local_time is None:
                return False, "Could not determine recipient timezone"
            
            # Check if within send window
            if self.is_within_send_window(local_time, windows):
                return True, f"Within send window (local time: {local_time.strftime('%I:%M %p')})"
            else:
                return False, f"Outside send window (local time: {local_time.strftime('%I:%M %p')})"
                
        except Exception as e:
            logger.error(f"Error in can_send_now: {e}")
            return False, f"Error: {str(e)}"
    
    def get_next_send_window(self, recipient: Dict, 
                            windows: List[Tuple[int, int]] = None) -> Optional[datetime]:
        """
        Calculate when the next send window opens for a recipient.
        
        Args:
            recipient: Dictionary containing location data
            windows: Optional custom send windows
            
        Returns:
            Datetime of next send window start or None
        """
        if windows is None:
            windows = self.DEFAULT_SEND_WINDOWS
        
        try:
            local_time = self.get_recipient_local_time(recipient)
            if not local_time:
                return None
            
            current_hour = local_time.hour
            
            # Find next window today
            for start_hour, _ in sorted(windows):
                if start_hour > current_hour:
                    next_window = local_time.replace(
                        hour=start_hour,
                        minute=0,
                        second=0,
                        microsecond=0
                    )
                    return next_window
            
            # If no windows left today, use first window tomorrow
            from datetime import timedelta
            tomorrow = local_time + timedelta(days=1)
            first_window_hour = min(start for start, _ in windows)
            next_window = tomorrow.replace(
                hour=first_window_hour,
                minute=0,
                second=0,
                microsecond=0
            )
            
            return next_window
            
        except Exception as e:
            logger.error(f"Error calculating next send window: {e}")
            return None


# Convenience functions for direct use
def detect_timezone(city: str = None, state: str = None, 
                   country: str = None) -> Optional[str]:
    """Convenience function to detect timezone."""
    scheduler = SendScheduler()
    return scheduler.detect_timezone(city=city, state=state, country=country)


def get_recipient_local_time(recipient: Dict) -> Optional[datetime]:
    """Convenience function to get recipient local time."""
    scheduler = SendScheduler()
    return scheduler.get_recipient_local_time(recipient)


def is_within_send_window(local_time: datetime, 
                          windows: List[Tuple[int, int]] = None) -> bool:
    """Convenience function to check send window."""
    scheduler = SendScheduler()
    return scheduler.is_within_send_window(local_time, windows)


def can_send_now(recipient: Dict) -> Tuple[bool, Optional[str]]:
    """Convenience function to check if can send now."""
    scheduler = SendScheduler()
    return scheduler.can_send_now(recipient)


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    
    # Test cases
    scheduler = SendScheduler()
    
    # Test 1: US recipient with state
    recipient_us = {
        'city': 'New York',
        'state': 'NY',
        'country': 'US'
    }
    can_send, reason = scheduler.can_send_now(recipient_us)
    print(f"US Recipient: can_send={can_send}, reason={reason}")
    
    # Test 2: International recipient
    recipient_uk = {
        'city': 'London',
        'country': 'UK'
    }
    can_send, reason = scheduler.can_send_now(recipient_uk)
    print(f"UK Recipient: can_send={can_send}, reason={reason}")
    
    # Test 3: Recipient with coordinates
    recipient_coords = {
        'city': 'San Francisco',
        'state': 'CA',
        'latitude': 37.7749,
        'longitude': -122.4194
    }
    local_time = scheduler.get_recipient_local_time(recipient_coords)
    print(f"SF Recipient local time: {local_time}")
    
    # Test 4: Next send window
    next_window = scheduler.get_next_send_window(recipient_us)
    print(f"Next send window: {next_window}")
