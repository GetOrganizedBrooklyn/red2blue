#!/usr/bin/env python3

import os
import pickle
import json
import flask
from werkzeug.exceptions import ServiceUnavailable
import google.oauth2.credentials
import google_auth_oauthlib.flow
import google.auth.transport.requests
import googleapiclient.discovery

TEXTER_LIST = 'TexterList'
CAMPAIGN_LIST = 'CampaignList'
AVAILABLE_TEXTS = 'AvailableTexts'

app = flask.Flask(__name__, template_folder='.')

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


secret = get_state('secret')
if not secret:
    secret = os.urandom(32)
    set_state('secret', secret)
app.secret_key = secret
SHEET_ID = get_state('sheet_id').decode().strip()
FORM_ID = get_state('form_id').decode().strip()

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
        raise ServiceUnavailable('This form is not active.')

    spreadsheets = googleapiclient.discovery.build('sheets', 'v4', credentials=creds).spreadsheets()
    return spreadsheets

def get_range(range):
    spreadsheets = get_spreadsheets()
    res = spreadsheets.values().get(spreadsheetId = SHEET_ID, range = range).execute()
    return res['values']

def get_column(range):
    data = get_range(range)
    data.pop(0)
    return [row[0] for row in data]

def get_texters():
    return get_column(TEXTER_LIST)

def get_campaigns():
    names = get_column(CAMPAIGN_LIST)
    counts = map(int, get_column(AVAILABLE_TEXTS))
    return zip(names, counts)

def oauth_flow(**kwargs):
    client_config = json.loads(get_state('client_secret'))
    return google_auth_oauthlib.flow.Flow.from_client_config(client_config,
            scopes=['https://www.googleapis.com/auth/spreadsheets.readonly'],
            redirect_uri = flask.url_for('oauth2callback', _external=True),
            **kwargs)

@app.route('/activate')
def activate():
    flow = oauth_flow()
    authorization_url, state = flow.authorization_url(
            access_type='offline')
            #include_granted_scopes='true')
    flask.session['state'] = state
    return flask.redirect(authorization_url)

@app.route('/oauth2callback')
def oauth2callback():
    state = flask.session['state']
    flow = oauth_flow(state=state)
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
    texters = get_texters()
    campaigns = get_campaigns()
    return flask.render_template('assignment-form.html', FORM_ID = FORM_ID,
            texters = texters,
            campaigns = campaigns)

@app.route('/fake')
def fake():
    return flask.render_template('assignment-form.html', FORM_ID = FORM_ID,
            texters = ['Josh Molho'],
            campaigns = [('MONDAY 10am ET: Lauren Underwood IL', 10000)])

