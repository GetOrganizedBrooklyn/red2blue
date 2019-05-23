#!/usr/bin/env python3

import os
import pickle
import json
import flask
import google.oauth2.credentials
import google_auth_oauthlib.flow
import google.auth.transport.requests
import googleapiclient.discovery

TEXTER_LIST = 'TexterList'
CAMPAIGN_LIST = 'CampaignList'
AVAILABLE_TEXTS = 'AvailableTexts'

app = flask.Flask(__name__)

redis_url = os.environ.get('REDIS_URL')
if redis_url:
    import redis
    redis = redis.from_url(redis_url)
else:
    redis = None

def get_state(var: str, default=None):
    """Load a named persistent state key from wherever is available: file on disk, environment variable."""
    if redis:
        val = redis.get(var)
        if val:
            return val
    try:
        with open(var, 'rb') as f:
            return f.read()
    except FileNotFoundError:
        try:
            return os.environ[var]
        except KeyError:
            return default

def set_state(var:str, data: bytes):
    """Set a persistent state key to the given value, which can later be read with `get_state`."""
    if redis:
        redis.set(var, data)
        return
    with open(var, 'wb') as f:
        f.write(data)


SHEET_ID = get_state('sheet_id').decode().strip()

class NotActive(Exception):
    def __init__(self):
        self.status_code = 503
        self.message = 'This form is not active.'

spreadsheets = None
def get_spreadsheets(creds=None):
    """Get the google sheets API for spreadsheets."""
    global spreadsheets
    if spreadsheets:
        return spreadsheets

    if creds is None:
        creds = get_state('credentials')
        if creds:
            creds = pickle.loads(creds)
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(google.auth.transport.requests.Request())
                set_state('credentials', pickle.dumps(creds))
    if not creds or not creds.valid:
        raise NotActive()

    spreadsheets = googleapiclient.discovery.build('sheets', 'v4', credentials=creds).spreadsheets()
    return spreadsheets

def oauth_flow(**kwargs):
    client_config = json.loads(get_state('client_secret'))
    return google_auth_oauthlib.flow.Flow.from_client_config(client_config,
            scopes=['https://www.googleapis.com/auth/spreadsheets.readonly'],
            redirect_uri = flask.url_for('oauth2callback', _external=True),
            **kwargs)

@app.route('/activate')
def activate():
    flow = oauth_flow()
    authorization_url, state = flow.authorization_url(access_type='offline')
    return flask.redirect(authorization_url)

@app.route('/oauth2callback')
def oauth2callback():
    flow = oauth_flow()
    flow.fetch_token(authorization_response = flask.request.url)
    creds = flow.credentials

    # make sure we can access the sheet and it has the necessary stuff
    spreadsheets = get_spreadsheets(creds)
    res = spreadsheets.get(spreadsheetId = SHEET_ID, fields = 'namedRanges').execute()
    ranges = {r['name']: r for r in res['namedRanges']}
    for r in (TEXTER_LIST, CAMPAIGN_LIST, AVAILABLE_TEXTS):
        ranges[r]

    set_state('credentials', pickle.dumps(creds))
    return flask.redirect('/')

@app.route('/')
def top():
    spreadsheets = get_spreadsheets()
    res = spreadsheets.get(spreadsheetId = SHEET_ID).execute()
    return flask.jsonify(res)

