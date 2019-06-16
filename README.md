# Red2Blue texting tracking tools

## Realtime assignment form

This is a python flask web app to serve a form for texters to pre-request assignments.
It pulls texters and campaigns from a google sheet, and submits back to that sheet.

### Configuration and state

You should first create a project and google OAuth2 credentials at https://console.developers.google.com/.
You'll need the `client_secret` json file for a web application.

You need to configure the google client API and provide a place to maintain state across requests.
There are a few ways to do this:

1. State and configuration can be maintained as files on disk, named by their key, suitable for a local deployment.
1. State and configuration can be stored in a redis database specified by `REDIS_URL` in the environment, suitable for heroku.
1. Configuration settings can be specified in the environment (as uppercase).

The following settings are required:

<dl>
<dt>sheet_id</dt>
<dd>The id of the google sheet to use.  You can find it in the URL of the sheet: https://docs.google.com/spreadsheets/d/<em>sheet_id</em>/edit?usp=sharing</dd>
<dt>client_secret</dt>
<dd>The client secret JSON from google, which should look like <code>{"web":{"client_id":...</code>.</dd>
</dl>

The application also creates a random `secret_key` if not set, and saves `sheet` after activation.

### Activation

The site needs to be activated with a google account that has access to the source sheet.
Visit the `/activate` URL to begin this process.
It should remain activated indefinitely, saving the state in the `sheet` key, which can be manually removed to deactivate the form.

### Quickstart for local development

The setup generally follows Google's [python quickstart guide](https://developers.google.com/sheets/api/quickstart/python).

1. Clone this repo: `git clone https://github.com/GetOrganizedBrooklyn/red2blue`
1. Get `client_secret` json from Google:
   1. Go to https://console.developers.google.com/
   1. Create a new project (if necessary)
   1. Add the Google Sheets API to the project through the Library.
   1. Under Credentials, create "OAuth (2.0) client ID" for a "Web application".
   1. Add to Authorized redirect URIs `https://localhost:8283/oauth2callback` (no JavaScript origins)
   1. Download JSON for this client and save it as `client_secret` (no extension) in the project directory
1. Setup a python3 environment
   1. Optionally create and activate a virtual env:
      ```
      python3 -m venv venv
      source venv/bin/activate
      ```
   1. Install the dependencies: `pip3 install -r requirements.txt`
1. Make sure `sheet_id` reference the google sheet you want to use, and that your google account has access to it.
1. Run flask for local development
   1. Create a `.flaskenv` file containing:
      ```
      FLASK_APP=assignment-form
      FLASK_ENV=development
      FLASK_RUN_HOST=localhost
      FLASK_RUN_PORT=8283
      FLASK_RUN_CERT=adhoc
      ```
   1. Run `flask run`
1. Open a browser and go to https://localhost:8283/.  You should see a "not activated" message.
1. Activate the form by going to https://localhost:8283/activate and signing in through google.
