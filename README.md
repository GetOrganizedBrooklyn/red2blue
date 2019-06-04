# Red2Blue texting tracking tools

## Realtime assignment form

This is a python flask web app to serve a form for texters to pre-request assignments.
It pulls texters and campaigns from a google sheet, and submits back to a google form for that sheet.

### Configuration and state

You should first create a project and google OAuth2 credentials at https://console.developers.google.com/.
You'll need the `client_secret` json file for a web application.

You need to configure the google client API and provide a place to maintain state across requests.
There are a few ways to do this:

1. State and configuration can be maintained as files on disk, named by their key, suitable for a local deployment.
1. State and configuration can be stored in a redis database specified by `REDIS_URL` in the environment, suitable for heroku.
1. Configuration settings can be specified in the environment.

The following settings are required:

<dl>
<dt>sheet_id</dt>
<dd>The id of the google sheet to pull from.  You can find it in the URL of the sheet: https://docs.google.com/spreadsheets/d/<em>sheet_id</em>/edit?usp=sharing</dd>
<dt>form_id</dt>
<dd>The id of the google form to submit to.  You can find it in the URL of the form: https://docs.google.com/forms/d/<em>form_id</em>/edit?usp=sharing</dd>
<dt>client_secret</dt>
<dd>The client secret JSON from google, which should look like <code>{"web":{"client_id":...</code>.</dd>
</dl>

The application also creates a random `secret` and `credentials` after activation.

### Activation

The site needs to be activated with a google account that has access to the source sheet.
Visit the `/activate` URL to begin this process.
It should remain activated for some amount of time (TBD)...
