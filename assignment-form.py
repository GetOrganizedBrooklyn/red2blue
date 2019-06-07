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
ACTIVE_STATE = 'ActiveRange'
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
FORM_ID = get_state('form_id').decode().strip()

class Sheet():
    SHEET_ID = get_state('sheet_id').decode().strip()
    sheet = None

    @staticmethod
    def set_creds(creds):
        set_state('credentials', pickle.dumps(creds))

    @staticmethod
    def get_creds(creds = None):
        if creds is None:
            creds = get_state('credentials')
            if creds:
                creds = pickle.loads(creds)
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(google.auth.transport.requests.Request())
                    Sheet.set_creds(creds)

        if not creds or not creds.valid:
            raise ServiceUnavailable('This form is not active.')

        return creds

    @staticmethod
    def build_api(creds):
        return googleapiclient.discovery.build('sheets', 'v4', credentials=creds).spreadsheets()

    def __init__(self, creds=None, sheet_id=SHEET_ID):
        self.sheet_id = sheet_id
        self.creds = self.get_creds(creds)
        self.api = self.build_api(self.creds)

    @classmethod
    def get(self):
        """Get or create the global cached sheet."""
        if not self.sheet:
            self.sheet = Sheet()
        return self.sheet

    @classmethod
    def set(self, sheet):
        """Set the global cached sheet."""
        self.sheet = sheet
        self.set_creds(sheet.creds)

    def use(self):
        """Cache this sheet as the global one."""
        self.set(self)

    def get_sheet(self, **kwargs):
        return self.api.get(spreadsheetId = self.sheet_id, **kwargs).execute()

    def get_range(self, range):
        res = self.api.values().get(spreadsheetId = self.sheet_id, range = range).execute()
        return res['values']

    def get_column(self, range):
        data = self.get_range(range)
        data.pop(0)
        return [row[0] for row in data]

    def get_texters(self):
        return self.get_column(TEXTER_LIST)

    def get_campaigns(self):
        return [(name, int(count))
                for name, active, count
                in zip(self.get_column(CAMPAIGN_LIST), self.get_column(ACTIVE_STATE), self.get_column(AVAILABLE_TEXTS))
                if active == 'Assigning']

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
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent')
    flask.session['state'] = state
    return flask.redirect(authorization_url)

@app.route('/oauth2callback')
def oauth2callback():
    state = flask.session['state']
    flow = oauth_flow(state=state)
    flow.fetch_token(authorization_response = flask.request.url)
    creds = flow.credentials

    # make sure we can access the sheet and it has the necessary stuff
    sheet = Sheet(creds=creds)
    res = sheet.get_sheet(fields = 'namedRanges')
    ranges = {r['name']: r for r in res['namedRanges']}
    for r in (TEXTER_LIST, CAMPAIGN_LIST, ACTIVE_STATE, AVAILABLE_TEXTS):
        ranges[r]

    sheet.use()
    return flask.redirect('/')

@app.route('/')
def top():
    sheet = Sheet.get()
    texters = sheet.get_texters()
    campaigns = sheet.get_campaigns()
    return flask.render_template('assignment-form.html', FORM_ID = FORM_ID,
            texters = texters,
            campaigns = campaigns)
