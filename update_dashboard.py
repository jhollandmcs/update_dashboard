import os, json
from sys import exit
from datetime import datetime

# ================================================================= #

# Load config

try:
    with open("config.json") as f:
        config = json.load(f)
except FileNotFoundError:
    print("ERROR: no config file found. Aborting.")
    exit()

client_id = config['id']
client_secret = config['secret']
url = config['url']
target_path = config['target_path']

# Scan target directory

target_files = os.listdir(target_path)
files_to_remove = []
files_to_replace = []

# Ignore files whose name and timestamp is unchanged from previous run

try:
    with open("known_files.json", "r") as f:
        try:
            data = json.load(f)
            for item in data:
                if item['name'] in target_files:
                    full_path = os.path.join(target_path, item['name'])
                    if os.path.getmtime(full_path) == item['timestamp']:
                        target_files.remove(item['name'])
                    else:
                        files_to_replace.append(item['formatname'])
                else:
                    files_to_remove.append(item['formatname'])
        except json.JSONDecodeError:
            print("WARNING: known_files.json could not be read. No files will be ignored.")
            pass # if we can't read the JSON, we just ignore it
except FileNotFoundError:
    pass # if the file doesn't exist, we can also just move on. it will be written later.

# If no new files, do nothing

if len(target_files) == 0 and len(files_to_remove) == 0:
    print("No changes found, exiting")
    exit()
else:
    print(f"""List of changes:\n\t
        {len(target_files)} files to add: {target_files}\n\t
        {len(files_to_replace)} files to replace: {files_to_replace}\n\t
        {len(files_to_remove)} files to remove: {files_to_remove}""")


# ================================================================= #

# Begin API code

import requests
from utils import *

# Get access token

token_url = f"{url}/authorize/access_token"

try:
    res = requests.post(
        token_url,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials"
        }
    )
    res.raise_for_status()
    info = res.json()
    token = info['access_token']
    # print("Access token:", token)
except requests.exceptions.RequestException as e:
    print(f"Error obtaining token: {e}")
    raise SystemExit(1)

headers = {
    "Authorization": f"Bearer {token}"
}



# Get playlist id

res = requests.get(f"{url}/playlist", headers=headers)
playlists = res.json()
for pl in playlists:
    if pl['name'] == "Shop Dashboard Test":
        playlist_id = pl['playlistId']
        print(f"found playlist: {pl}")

# Upload new media + get new media ids

def get_format_name(fn):
    strtime = str(datetime.now()).replace('-', '').replace(':', '').replace(' ', '')[:14]
    return f"_api_{os.path.splitext(fn)[0].replace(' ', '')[:10]}_{strtime}"

new_media_ids = []
new_format_names = dict() # store for writing to known_files later

for tf in target_files:
    with open(os.path.join(target_path, tf), "rb") as f:
        files = {"files": f}
        format_name = get_format_name(tf)
        new_format_names[tf] = format_name
        data = {
            "name": format_name,
            "type": "video",
            "updateInLayout": 1
        }
        res = requests.post(f"{url}/library", headers=headers, files=files, data=data)
    res.raise_for_status()
    media_info = res.json()
    print("Uploaded media: ", media_info)
    new_media_ids.append(media_info["files"][0]['mediaId'])

# Get old media ids

media_dict = find_media_ids_for_names(url, headers, files_to_replace + files_to_remove)
old_media_ids = [mid for ids in media_dict.values() for mid in ids]

# Assign media to playlist

info = assign_media_to_playlist(url, headers, playlist_id, new_media_ids, old_media_ids)
print(f"info:\n\tdeleted: {info['deleted']}\n\tassigned: {info['assigned']}\n\tnotes: {info['notes']}")

# Write files and timestamps to known_files.json

all_files = os.listdir(target_path)
out = []
for f in all_files:
    out.append(
        {
            "name": f, 
            "timestamp": os.path.getmtime(os.path.join(target_path, f)),
            "formatname": new_format_names[f]
        }
    )
with open("known_files.json", "w") as f:
    f.write(json.dumps(out))
    print(f"Wrote {len(out)} files to known_files.json")