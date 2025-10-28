Imou Recorder and Gdrive Synchronizer
---

Start auth
Start recorder
Start uploader

/opt/homebrew/bin/python3.11 auth_google_drive.py

 pip install -r requirements.txt   
 python3 auth_google_drive.py
 python3 record_

----

Create/enable a Google Cloud project

Visit https://console.cloud.google.com/ and sign in.
Select an existing project or create a new one.
Enable the Drive API

In the left sidebar, go to APIs & Services → Library.
Search “Google Drive API” and click it.
Press Enable.
Set up OAuth consent

Still under APIs & Services, open OAuth consent screen.
Choose Internal (workspace only) or External (most common).
Fill in the required fields—App name, support email, developer email—and save.
Add scopes like .../auth/drive.file or .../auth/drive if prompted (Drive API requires it).
Create OAuth client credentials

Go to Credentials → Create Credentials → OAuth client ID.
Application type: choose Desktop App (PyDrive2 expects this for LocalWebserverAuth).
Name it (e.g. PyDrive2 Recorder) and click Create.
Download the client_secret_<id>.json. Save it into your project folder and rename to client_secrets.json (PyDrive2 default).
Generate mycreds.json with PyDrive2

Ensure client_secrets.json is alongside your script.
Run python upload_videos.py or record_cameras.py once, or better, a small auth script using PyDrive2’s GoogleAuth.
On first run, PyDrive2 opens a browser asking you to sign in and authorize the app. Approve with the Google account whose Drive will store the videos.
After authorizing, PyDrive2 creates mycreds.json in the working directory. This file contains refresh tokens and is what you point to in conf_upload.yaml (google_drive.credentials_file).
Future refresh

PyDrive2 automatically refreshes the token when expired and updates mycreds.json, so keep it writable.
If you revoke the app or change the client secret, delete mycreds.json and rerun the auth flow.
Important: client_secrets.json (from Google Cloud) and mycreds.json (generated locally) are both sensitive; keep them out of version control and share only when necessary.