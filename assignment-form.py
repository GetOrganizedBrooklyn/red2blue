#!/usr/bin/env python3

import os
import pickle
import time
import json
import flask
from werkzeug.exceptions import ServiceUnavailable, FailedDependency
import google.oauth2.credentials
import google_auth_oauthlib.flow
import google.auth.transport.requests
import googleapiclient.discovery
import wtforms

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
    TEXTER_LIST = 'TexterList'
    CAMPAIGN_LIST = 'CampaignList'
    ACTIVE_STATE = 'ActiveRange'
    AVAILABLE_TEXTS = 'AvailableTexts'
    RESPONSES = 'Responses'
    ALL_RANGES = [TEXTER_LIST, CAMPAIGN_LIST, ACTIVE_STATE, AVAILABLE_TEXTS, RESPONSES]
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
        self.texters = None
        self.campaigns = None

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
        if self.texters is None:
            self.texters = self.get_column(self.TEXTER_LIST)
        return self.texters

    def get_campaigns(self):
        if self.campaigns is None:
            self.campaigns = {name: int(count)
                    for name, active, count
                    in zip(self.get_column(self.CAMPAIGN_LIST), self.get_column(self.ACTIVE_STATE), self.get_column(self.AVAILABLE_TEXTS))
                    if active == 'Assigning'}
        return self.campaigns

    def add_response(self, *values):
        self.api.values().append(spreadsheetId = self.sheet_id, range = self.RESPONSES,
                valueInputOption = 'USER_ENTERED',
                body = {'values': [values]}).execute()

def oauth_flow(**kwargs):
    client_config = json.loads(get_state('client_secret'))
    return google_auth_oauthlib.flow.Flow.from_client_config(client_config,
            scopes=['https://www.googleapis.com/auth/spreadsheets'],
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
    for r in Sheet.ALL_RANGES:
        if r not in ranges:
            raise FailedDependency('Form is missing named range: ' + r)

    sheet.use()
    return flask.redirect('/')

class Form(wtforms.Form):
    texter   = wtforms.SelectField('Texter name')
    campaign = wtforms.SelectField('Campaign requested')
    number   = wtforms.IntegerField('Number of texts requested',
            validators = [wtforms.validators.NumberRange(300, 1000)])
    check1   = wtforms.BooleanField('I have joined the ThruText account for the assignment that I am requesting',
            validators = [wtforms.validators.DataRequired()])
    check2   = wtforms.BooleanField('I will not "ghost!"  I will check ThruText for replies AT LEAST twice a day through November 5 and AT LEAST four times on November 6!',
            validators = [wtforms.validators.DataRequired()])

    def __init__(self, formdata=None, **kwargs):
        super(Form, self).__init__(formdata, **kwargs)
        self.number.widget.min = 300
        self.number.widget.max = 1000

@app.route('/', methods=['GET', 'POST'])
def top():
    sheet = Sheet.get()
    texters = sheet.get_texters()
    campaigns = sheet.get_campaigns()
    form = Form(flask.request.form)
    form.texter.choices = [(texter, texter) for texter in texters]
    form.campaign.choices = [(name, name) for name, number in campaigns.items() if number > 0]
    try:
        number = campaigns[form.campaign.data]
        form.number.validators[0].max = min(1000, number)
        form.number.validators[0].min = min(300, number)
    except KeyError:
        pass
    if flask.request.method == 'POST' and form.validate():
        sheet.add_response(time.strftime('%D %T'), form.texter.data, form.campaign.data, form.number.data)
        return 'Submitted'
    return flask.render_template('assignment-form.html', form = form,
            campaigns = campaigns)
