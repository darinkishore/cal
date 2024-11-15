from utils import NylasScheduler, EventData
# Example usage of the NylasScheduler class

# Initialize the scheduler
scheduler = NylasScheduler(
    api_key='your_nylas_api_key',
    grant_id='your_grant_id',
    user_timezone='America/New_York',
    calendar_id='primary'
)

# Create an event
event_data = EventData(
    title='Team Meeting',
    when='2023-10-15T10:00:00',
    duration_minutes=60,
    location='Conference Room A',
    description='Monthly team sync-up meeting.',
    attendees=['alice@example.com', 'bob@example.com']
)

created_event = scheduler.create_event(event_data)
print(f'Created event ID: {created_event.id}')

# Get today's events
todays_events = scheduler.get_todays_events()
for event in todays_events:
    print(f'Event: {event.title} at {event.start_time}')

# Delete an event
scheduler.delete_event(created_event.id)
print(f'Deleted event ID: {created_event.id}')

# Undo the last action (deletion)
undo_message = scheduler.undo_last_action()
print(undo_message)
