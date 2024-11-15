# calendar utils

## installation

```bash
python -m venv .venv
pip install .
``` 

example usage is in `example.py`

- **API Keys and Grant IDs**: Replace `'your_nylas_api_key'` and `'your_grant_id'` with your actual Nylas API key and grant ID.

- **Error Handling**: The code includes exception handling for common Nylas API errors. You may want to expand upon this based on your application's needs.

- **Time Zones**: The `user_timezone` parameter allows you to set the default time zone for all date and time operations.
