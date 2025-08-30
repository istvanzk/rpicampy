#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Perform Dropbox authentication, token refresh, and save to local file.
See https://www.dropboxforum.com/discussions/101000014/dropbox-exceptions-autherror-expired-access-token/580407
and https://github.com/dropbox/dropbox-sdk-python/blob/main/example/oauth/commandline-oauth-scopes.py
"""

from dropbox import Dropbox, DropboxOAuth2FlowNoRedirect
import pickle

# The file to store the tokens
TOKEN_FILE = 'tokens.pkl'

# The tokens dictionary
tokens = {}

#
# Try to load existing token file
#
try:
    with open(TOKEN_FILE, 'rb') as f:
        tokens = pickle.load(f)
    print("Token loaded from {TOKEN_FILE}")

except Exception as e:
    print("No token file found, starting new authorization flow")
    print(f"\t{e}")

    #
    # New Authorizaton flow
    #
    print("0a. Copy the app key and app secret. These are available after you have generated an app in the Dropbox developer console.")
    tokens['app_key'] = input("0b. Enter the app_key here: ").strip()
    tokens['app_secret'] = input("0c. Enter the app_secret here: ").strip()

    print("1. Start new authorization flow...")
    auth_flow = DropboxOAuth2FlowNoRedirect(
        tokens['app_key'], # consumer_key
        consumer_secret=tokens['app_secret'],
        token_access_type='offline',
        scope=['files.metadata.read', 'account_info.read', 'files.content.read', 'files.content.write'],
        include_granted_scopes='user'
    )

    authorize_url = auth_flow.start()
    print("2. Go to: " + authorize_url)
    print("3. Click \"Allow\" (you might have to log in first).")
    print("4a. Copy the authorization code.")
    auth_code = input("4b. Enter the authorization code here: ").strip()

    print("4. Finalize authorization...")
    try:
        tokens["oauth_result"] = auth_flow.finish(auth_code)
        # Check if authorization has all granted user scopes
        assert 'account_info.read' in tokens["oauth_result"].scope
        assert 'files.metadata.read' in tokens["oauth_result"].scope
        assert 'files.content.read' in tokens["oauth_result"].scope
        assert 'files.content.write' in tokens["oauth_result"].scope

        # Save to a pkl file
        with open(TOKEN_FILE, 'wb') as f:
            pickle.dump(tokens, f)
        print("5. Token saved to {TOKEN_FILE}")

    except Exception as e:
        print('Error: %s' % (e,))
        exit(1)


print("OAuth result:")
print(f"\t{tokens['oauth_result'].scope}")
print(f"\t{tokens['oauth_result'].expires_at}")
print(f"\t{tokens['oauth_result'].refresh_token}")

print("Instantiate client...")
dbx = Dropbox(
    oauth2_access_token=tokens["oauth_result"].access_token,
    user_agent='RPiCamPy/6.0',
    oauth2_access_token_expiration=tokens["oauth_result"].expires_at,
    oauth2_refresh_token=tokens["oauth_result"].refresh_token,
    app_key=tokens['app_key'],
    app_secret=tokens['app_secret']
)

print("Successfully instantiated client, checking and refreshing access token if needed...")
dbx.check_and_refresh_access_token()

print("Getting current account info...")
dbx.users_get_current_account()

print("Dropbox client was successfully set up")