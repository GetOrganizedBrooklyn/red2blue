#!/usr/bin/env python3

from typing import Optional, List, Dict
import os
import pickle
import time
import json
import flask
import google.oauth2.credentials
import google_auth_oauthlib.flow
import google.auth.transport.requests
import googleapiclient.discovery
import wtforms

app = flask.Flask(__name__, template_folder='web', static_folder='web')

redis_url = os.environ.get('REDIS_URL')
if redis_url:
    import redis
    redis = redis.from_url(redis_url)
else:
    redis = None

def get_state(var: str, default=None) -> Optional[bytes]:
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
            return os.environ[var.upper()]
        except KeyError:
            return default

def set_state(var: str, data: bytes) -> None:
    """Set a persistent state key to the given value, which can later be read with `get_state`."""
    if redis:
        redis.set(var, data)
        return
    with open(var, 'wb') as f:
        f.write(data)

def inactive():
    flask.abort(503, 'This form is not active.')

secret = get_state('secret_key')
if not secret:
    secret = os.urandom(32)
    set_state('secret_key', secret)
app.secret_key = secret

class Sheet():
    SHEET_ID = get_state('sheet_id').decode().strip()
    TEXTER_LIST = 'TexterList'
    CAMPAIGN_LIST = 'CampaignList'
    ACTIVE_STATE = 'ActiveRange'
    AVAILABLE_TEXTS = 'AvailableTexts'
    RESPONSES = 'Responses'
    ALL_RANGES = [TEXTER_LIST, CAMPAIGN_LIST, ACTIVE_STATE, AVAILABLE_TEXTS, RESPONSES]
    sheet = None

    def update(self):
        if Sheet.sheet is self:
            set_state('sheet', pickle.dumps(self))

    def use(self) -> None:
        """Cache this sheet as the global one."""
        Sheet.sheet = self
        self.update()

    @classmethod
    def load(self) -> Optional["Sheet"]:
        """Get or create the global cached sheet."""
        if not self.sheet:
            sheet = get_state('sheet')
            if sheet:
                sheet = pickle.loads(sheet)
            if sheet and sheet.sheet_id == Sheet.SHEET_ID:
                sheet.use()
        if not self.sheet:
            set_state('sheet', b'')
        return self.sheet

    @classmethod
    def get(self) -> "Sheet":
        sheet = self.load()
        if not sheet:
            inactive()
        return sheet

    def __init__(self, creds: google.oauth2.credentials.Credentials, sheet_id: str=SHEET_ID):
        self.sheet_id = sheet_id
        self._creds = creds
        self._api = None
        self._texters = None
        self._campaigns = None
        self.channel = None
        self.expires = None

    def __getstate__(self):
        return {
            'creds':   self._creds,
            'sheet':   self.sheet_id,
            'channel': self.channel,
            'expires': self.expires
        }

    def __setstate__(self, state):
        self.__init__(state['creds'], state['sheet'])
        self.channel = state['channel']
        self.expires = state['expires']

    @property
    def creds(self) -> google.oauth2.credentials.Credentials:
        """Retrieve and refresh credentials if necessary."""
        creds = self._creds

        if creds and creds.expired and creds.refresh_token:
            creds.refresh(google.auth.transport.requests.Request())
            self.creds = creds

        if not creds or not creds.valid:
            inactive()

        return creds

    @creds.setter
    def creds(self, creds: google.oauth2.credentials.Credentials) -> None:
        self._creds = creds
        self.update()

    @property
    def api(self):
        if not self._api:
            self._api = googleapiclient.discovery.build('sheets', 'v4', credentials=self.creds).spreadsheets()
        return self._api

    @property
    def driveapi(self):
        return googleapiclient.discovery.build('drive', 'v3', credentials=self.creds)

    def watch(self) -> None:
        files = self.driveapi.files()
        self.channel = os.urandom(16).hex()
        res = files.watch(fileId = self.sheet_id,
                body = {
                    'id': self.channel,
                    'type': 'web_hook',
                    'address': flask.url_for('watch', _external=True)
                }).execute()
        self.expires = int(res['expiration'])/1000
        self.update()

    def modified(self):
        self._texters = None
        self._campaigns = None

    def rewatch(self) -> None:
        if self.expires is None or self.expires < time.time():
            self.modified()
            self.watch()

    def get_sheet(self, **kwargs):
        return self.api.get(spreadsheetId = self.sheet_id, **kwargs).execute()

    def get_range(self, range: str) -> List[List[str]]:
        res = self.api.values().get(spreadsheetId = self.sheet_id, range = range).execute()
        return res['values']

    def get_column(self, range: str) -> List[str]:
        data = self.get_range(range)
        data.pop(0)
        return [row[0] for row in data]

    def get_texters(self) -> List[str]:
        return self.get_column(self.TEXTER_LIST)

    @property
    def texters(self) -> List[str]:
        self.rewatch()
        if not self._texters:
            self._texters = self.get_texters()
        return self._texters

    def get_campaigns(self) -> Dict[str, int]:
        return {name: int(count)
                for name, active, count
                in zip(self.get_column(self.CAMPAIGN_LIST), self.get_column(self.ACTIVE_STATE), self.get_column(self.AVAILABLE_TEXTS))
                if active == 'Assigning'}

    @property
    def campaigns(self) -> Dict[str, int]:
        self.rewatch()
        if not self._campaigns:
            self._campaigns = self.get_campaigns()
        return self._campaigns

    def add_response(self, *values) -> None:
        values = list(values)
        values.insert(0, time.strftime('%D %T'))
        self.api.values().append(spreadsheetId = self.sheet_id, range = self.RESPONSES,
                valueInputOption = 'USER_ENTERED',
                body = {'values': [values]}).execute()

def oauth_flow(**kwargs):
    client_config = json.loads(get_state('client_secret'))
    return google_auth_oauthlib.flow.Flow.from_client_config(client_config,
            scopes=['https://www.googleapis.com/auth/spreadsheets',
                    'https://www.googleapis.com/auth/drive.metadata.readonly'],
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
    sheet = Sheet(creds)
    res = sheet.get_sheet(fields = 'namedRanges')
    ranges = {r['name']: r for r in res['namedRanges']}
    for r in Sheet.ALL_RANGES:
        if r not in ranges:
            return 'Form is missing named range: ' + r, 424
    sheet.add_response('', 'activating', '', flask.url_for('activate', _external=True))

    sheet.use()
    return flask.redirect('/')

class Form(wtforms.Form):
    texter   = wtforms.SelectField('Texter name')
    campaign = wtforms.SelectField('Campaign requested')
    number   = wtforms.IntegerField('Number of texts requested')
    check1   = wtforms.BooleanField('I have joined the ThruText account for the assignment that I am requesting',
            validators = [wtforms.validators.DataRequired()])
    check2   = wtforms.BooleanField('I will not "ghost!"  I will check ThruText for replies AT LEAST twice a day through November 5 and AT LEAST four times on November 6!',
            validators = [wtforms.validators.DataRequired()])

@app.route('/', methods=['GET', 'POST'])
def top():
    sheet = Sheet.get()
    form = Form(flask.request.form)
    form.texter.choices = [(texter, texter) for texter in sheet.texters]
    form.campaign.choices = [(name, name) for name, number in sheet.campaigns.items() if number > 0]
    try:
        number = sheet.campaigns[form.campaign.data]
    except KeyError:
        number = 1000
    form.number.validators.append(wtforms.validators.NumberRange(min(300, number), min(1000, number)))
    if flask.request.method == 'POST' and form.validate():
        sheet.add_response(form.texter.data, form.campaign.data, form.number.data)
        return 'Submitted'
    return flask.render_template('assignment-form.html', form = form,
            sheet = sheet)

@app.route('/watch', methods=['POST'])
def watch():
    state = flask.request.headers['X-Goog-Resource-State']
    channel = flask.request.headers['X-Goog-Channel-ID']
    #token = flask.request.headers['X-Goog-Channel-Token']
    changed = flask.request.headers.get('X-Goog-Changed', '').split(',')
    sheet = Sheet.load()
    if not sheet or sheet.channel != channel:
        return '', 410
    if state == 'update' and 'content' in changed:
        sheet.modified()
    return '', 204
