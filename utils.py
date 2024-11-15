# utils.py

import logging
import os
from datetime import UTC
from typing import Any, List, Optional

import pendulum
from bs4 import BeautifulSoup
from fuzzywuzzy import fuzz
from nylas import Client
from nylas.models.errors import NylasApiError, NylasOAuthError, NylasSdkTimeoutError
from nylas.models.events import (
    CreateDate,
    CreateEventRequest,
    CreateParticipant,
    CreateTimespan,
    Date,
    Datespan,
    ListEventQueryParams,
    Time,
    Timespan,
)
from nylas.models.events import Event as NylasEvent
from pydantic import BaseModel
from pydantic_extra_types.pendulum_dt import DateTime

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class EventData(BaseModel):
    title: str
    when: str  # ISO 8601 datetime string
    duration_minutes: int = 30
    location: Optional[str] = None
    description: Optional[str] = None
    attendees: Optional[List[str]] = None
    metadata: Optional[dict[str, Any]] = None
    visibility: Optional[str] = None
    busy: Optional[bool] = None
    capacity: Optional[int] = None
    hide_participants: Optional[bool] = None
    all_day: bool = False


class Event(BaseModel):
    id: str
    title: str
    start_time: Optional[DateTime] = None
    end_time: Optional[DateTime] = None
    all_day: bool = False
    location: Optional[str] = None
    description: Optional[str] = None
    attendees: Optional[List[str]] = None
    metadata: Optional[dict[str, Any]] = None


class ActionHistoryEntry(BaseModel):
    action: str
    event_id: str
    event_data: Optional[NylasEvent] = None


def html_to_plain_text(html_content: Optional[str]) -> Optional[str]:
    if html_content:
        soup = BeautifulSoup(html_content, 'html.parser')
        return soup.get_text(separator=' ', strip=True)
    return None


def parse_when(when_data: Date | Timespan | Datespan | Time, user_timezone: str) -> tuple[Optional[DateTime], Optional[DateTime], bool]:
    all_day = False
    start_time = end_time = None

    if isinstance(when_data, Time):
        time_ts = when_data.time
        timezone = when_data.timezone
        start_time = end_time = pendulum.from_timestamp(time_ts, tz=UTC).in_timezone(timezone)
    elif isinstance(when_data, Timespan):
        start_ts, end_ts = when_data.start_time, when_data.end_time
        start_timezone = when_data.start_timezone
        end_timezone = when_data.end_timezone
        start_time = pendulum.from_timestamp(start_ts, tz=UTC).in_timezone(start_timezone)
        end_time = pendulum.from_timestamp(end_ts, tz=UTC).in_timezone(end_timezone)
    elif isinstance(when_data, Date):
        date_str = when_data.date
        start_time = pendulum.parse(date_str, tz=user_timezone).start_of('day')
        end_time = start_time.end_of('day')
        all_day = True
    elif isinstance(when_data, Datespan):
        start_date_str, end_date_str = when_data.start_date, when_data.end_date
        start_time = pendulum.parse(start_date_str, tz=user_timezone).start_of('day')
        end_time = pendulum.parse(end_date_str, tz=user_timezone).end_of('day')
        all_day = True
    else:
        raise ValueError('Unknown when_data type.')

    return start_time, end_time, all_day


def parse_nylas_event(event: NylasEvent, user_timezone: str) -> Event:
    start_time, end_time, all_day = parse_when(event.when, user_timezone)
    attendees = [participant.email for participant in event.participants] if event.participants else None
    return Event(
        id=event.id,
        title=event.title,
        start_time=start_time,
        end_time=end_time,
        all_day=all_day,
        location=event.location,
        description=html_to_plain_text(event.description),
        attendees=attendees,
        metadata=event.metadata or None,
    )


def fuzzy_search_events(events: List[Event], search_query: str, threshold: int = 80) -> List[Event]:
    matching_events = []
    for event in events:
        similarity = fuzz.partial_ratio(search_query.lower(), event.title.lower())
        if similarity >= threshold:
            matching_events.append(event)

    matching_events.sort(
        key=lambda e: fuzz.partial_ratio(search_query.lower(), e.title.lower()),
        reverse=True,
    )

    return matching_events


class NylasScheduler:
    def __init__(self, api_key: str, grant_id: str, user_timezone: str = 'UTC', calendar_id: str = 'primary'):
        self.nylas = Client(api_key=api_key)
        self.grant_id = grant_id
        self.user_timezone = user_timezone
        self.calendar_id = calendar_id
        self.action_history: List[ActionHistoryEntry] = []

    def create_event(self, event_data: EventData) -> Event:
        try:
            parsed_datetime = pendulum.parse(event_data.when, tz=self.user_timezone)
            if not parsed_datetime:
                raise ValueError("Could not parse 'when' field.")

            start_time = parsed_datetime
            end_time = start_time.add(minutes=event_data.duration_minutes)

            logger.info(f'Parsed datetime: {parsed_datetime}')

            # Build the When object
            if event_data.all_day:
                when = CreateDate(date=start_time.to_date_string())
            else:
                when = CreateTimespan(
                    start_time=int(start_time.timestamp()),
                    end_time=int(end_time.timestamp()),
                    start_timezone=self.user_timezone,
                    end_timezone=self.user_timezone,
                )

            # Build participants
            participants = [CreateParticipant(email=email) for email in event_data.attendees] if event_data.attendees else None

            # Build CreateEventRequest without recurrence
            create_event_request = CreateEventRequest(
                title=event_data.title,
                when=when,
                location=event_data.location,
                description=event_data.description,
                participants=participants,
                metadata=event_data.metadata,
                visibility=event_data.visibility,
                busy=event_data.busy,
                capacity=event_data.capacity,
                hide_participants=event_data.hide_participants,
            )

            # Call nylas.events.create()
            response = self.nylas.events.create(
                self.grant_id,
                request_body=create_event_request,
                query_params={'calendar_id': self.calendar_id, 'notify_participants': 'false'},
            )

            logger.info(f'Response: {response}')

            # Log the action
            self.action_history.append(
                ActionHistoryEntry(
                    action='create',
                    event_id=response.data.id,
                )
            )

            return parse_nylas_event(response.data, self.user_timezone)
        except NylasApiError as e:
            logger.error(f'Nylas API error while creating event: {e}')
            raise
        except NylasOAuthError as e:
            logger.error(f'Nylas OAuth error while creating event: {e}')
            raise
        except NylasSdkTimeoutError as e:
            logger.error(f'Timeout error while creating event: {e}')
            raise
        except Exception as e:
            logger.error(f'Unexpected error while creating event: {e}')
            raise

    def delete_event(self, event_id: str) -> None:
        try:
            # Fetch the event details before deletion
            event_response = self.nylas.events.find(
                self.grant_id, event_id, query_params={'calendar_id': self.calendar_id}
            )
            event = event_response.data
            logger.info(f'Event Response: {event}')
            # Delete the event
            delete_response = self.nylas.events.destroy(
                self.grant_id, event_id, query_params={'calendar_id': self.calendar_id}
            )
            logger.info(f'Delete Response: {delete_response}')
            # Log the action
            self.action_history.append(
                ActionHistoryEntry(
                    action='delete',
                    event_id=event_id,
                    event_data=event,
                )
            )
        except NylasApiError as e:
            logger.error(f'Nylas API error while deleting event: {e.message}')
            raise
        except NylasOAuthError as e:
            logger.error(f'Nylas OAuth error while deleting event: {e.error_description}')
            raise
        except NylasSdkTimeoutError as e:
            logger.error(f'Timeout error while deleting event: {e}')
            raise
        except Exception as e:
            logger.error(f'Unexpected error while deleting event: {e}')
            raise

    def undo_last_action(self) -> str:
        if not self.action_history:
            return 'No actions to undo.'

        last_action = self.action_history.pop()
        logger.info(f'Last Action: {last_action}')
        action = last_action.action
        event_id = last_action.event_id

        if action == 'create':
            # Undo event creation by deleting the event
            delete_response = self.nylas.events.destroy(
                self.grant_id, event_id, query_params={'calendar_id': self.calendar_id}
            )
            logger.info(f'Delete Response: {delete_response}')
            return f'Creation of event {event_id} has been undone.'
        elif action == 'delete':
            # Undo event deletion by recreating the event
            event = last_action.event_data
            if event is None:
                return 'No event data to recreate the event.'
            # Remove read-only fields
            create_event_request = CreateEventRequest(
                title=event.title,
                when=event.when,
                location=event.location,
                description=event.description,
                participants=event.participants,
                metadata=event.metadata,
                visibility=event.visibility,
                busy=event.busy,
                capacity=event.capacity,
                hide_participants=event.hide_participants,
            )

            # Recreate the event
            recreated_event_response = self.nylas.events.create(
                self.grant_id,
                request_body=create_event_request,
                query_params={'calendar_id': self.calendar_id, 'notify_participants': 'false'},
            )
            recreated_event = recreated_event_response.data
            return f'Deletion of event {event_id} has been undone. New event ID is {recreated_event.id}.'
        else:
            return 'Unknown action.'

    def get_events(self, start: int, end: Optional[int] = None, limit: Optional[int] = None) -> List[Event]:
        try:
            logger.info(f'Calling get_events with Start: {start}, End: {end}, Limit: {limit}')
            query_params = ListEventQueryParams(
                calendar_id=self.calendar_id,
                start=start,
                expand_recurring=True,
                end=end or None,
                limit=limit or 100,
            )

            response = self.nylas.events.list(self.grant_id, query_params=query_params)

            logger.info(f'Response: {response}')

            events: List[NylasEvent] = response.data

            parsed_events = [parse_nylas_event(event, self.user_timezone) for event in events]

            logger.info(f'Parsed Events: {parsed_events}')

            return parsed_events
        except NylasApiError as e:
            logger.error(f'Nylas API error while fetching events: {e.message}')
            raise
        except NylasOAuthError as e:
            logger.error(f'Nylas OAuth error while fetching events: {e.error_description}')
            raise
        except NylasSdkTimeoutError as e:
            logger.error(f'Timeout error while fetching events: {e}')
            raise
        except Exception as e:
            logger.error(f'Unexpected error while fetching events: {e}')
            raise

    def get_todays_events(self, reference_date=None) -> List[Event]:
        if reference_date is None:
            reference_date = pendulum.now(self.user_timezone)
        today = reference_date.start_of('day')
        tomorrow = reference_date.end_of('day')
        return self.get_events(today.int_timestamp, tomorrow.int_timestamp)

    def get_next_three_days_events(self) -> List[Event]:
        today = pendulum.now(self.user_timezone).start_of('day')
        return self.get_events(today.int_timestamp, today.add(days=3).int_timestamp)

    def get_next_week_events(self) -> List[Event]:
        today = pendulum.now(self.user_timezone).start_of('day')
        return self.get_events(today.int_timestamp, today.add(weeks=1).int_timestamp)

    def get_all_events(self, start: int, end: Optional[int] = None) -> List[Event]:
        try:
            if end is None:
                end = pendulum.from_timestamp(start).add(years=1).int_timestamp

            all_events = []
            page_token = None

            while True:
                try:
                    if page_token:
                        query_params = ListEventQueryParams(
                            calendar_id=self.calendar_id,
                            start=start,
                            end=end,
                            limit=200,
                            page_token=page_token,
                        )
                    else:
                        query_params = ListEventQueryParams(
                            calendar_id=self.calendar_id,
                            start=start,
                            end=end,
                            limit=200,
                        )

                    response = self.nylas.events.list(
                        self.grant_id, query_params=query_params
                    )

                    events = response.data
                    all_events.extend([parse_nylas_event(event, self.user_timezone) for event in events])

                    if not response.next_cursor:
                        break

                    page_token = response.next_cursor
                except NylasApiError as e:
                    logger.error(f'Nylas API error while fetching events page: {e.message}')
                    raise
                except NylasOAuthError as e:
                    logger.error(f'Nylas OAuth error while fetching events page: {e.error_description}')
                    raise
                except NylasSdkTimeoutError as e:
                    logger.error(f'Timeout error while fetching events page: {e}')
                    raise
                except Exception as e:
                    logger.error(f'Unexpected error while fetching events page: {e}')
                    raise

            logger.info(f'Successfully retrieved {len(all_events)} events')
            return all_events

        except NylasApiError as e:
            logger.error(f'Nylas API error in get_all_events: {e.message}')
            raise
        except NylasOAuthError as e:
            logger.error(f'Nylas OAuth error in get_all_events: {e.error_description}')
            raise
        except NylasSdkTimeoutError as e:
            logger.error(f'Timeout error in get_all_events: {e}')
            raise
        except Exception as e:
            logger.error(f'Error in get_all_events: {e}')
            raise

    def cleanup_calendar(self, days_to_keep: int = 30) -> None:
        now = pendulum.now('UTC')
        start_date = now.subtract(years=10).start_of('day')
        end_date = now.subtract(days=days_to_keep).end_of('day')

        try:
            events_to_delete = self.get_all_events(start_date.int_timestamp, end_date.int_timestamp)

            for event in events_to_delete:
                try:
                    self.delete_event(event.id)
                    print(f'Deleted event: {event.title} (ID: {event.id})')
                except Exception as e:
                    logger.error(f'Error deleting event {event.id}: {e}')

            print(f'Cleanup complete. Deleted {len(events_to_delete)} events.')
        except Exception as e:
            logger.error(f'Error during calendar cleanup: {e}')
            raise
