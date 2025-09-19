import requests

def assign_media_to_playlist(base_url, headers, playlist_id, new_media_ids, old_media_ids, timeout=10):
    """
    Ensure a playlist ends up containing new_media_ids, removing any widgets
    that reference the old_media_ids when possible.

    Uses only documented Xibo API endpoints:
      - GET /playlist?playlistId={id}&embed=widgets,regions
      - DELETE /playlist/widget/{widgetId}
      - POST /playlist/library/assign/{playlistId}

    Returns a dict with keys:
      - 'deleted': list of (mediaId, widgetId) tuples actually deleted
      - 'assigned': the JSON response from the assign call (or None)
      - 'notes': informational messages
    """
    session = requests.Session()
    session.headers.update(headers)

    notes = []
    deleted = []

    # 1) Fetch playlist with widgets embedded (if the install supports it)
    try:
        r = session.get(
            f"{base_url}/playlist",
            params={"playlistId": playlist_id, "embed": "widgets,regions"},
            timeout=timeout
        )
        r.raise_for_status()
        plist = r.json()
    except requests.exceptions.RequestException as e:
        return {"deleted": deleted, "assigned": None, "notes": [f"Failed to fetch playlist: {e}"]}

    if not isinstance(plist, list) or not plist:
        return {"deleted": deleted, "assigned": None, "notes": [f"Playlist {playlist_id} not found or empty response: {plist}"]}

    p = plist[0]

    # 2) Build widget_map: mediaId -> [widgetId,...]
    widget_map = {}
    widgets = []
    # playlist may expose widgets under "widgets" or "newWidgets"
    widgets.extend(p.get("widgets", []) or [])
    widgets.extend(p.get("newWidgets", []) or [])

    for w in widgets:
        # widget id field may be widgetId or id depending on version
        wid = w.get("widgetId") or w.get("id")
        if not wid:
            continue
        # media ids may be in mediaIds (list) or mediaId (single) depending on version
        mids = []
        if "mediaIds" in w and w.get("mediaIds"):
            mids = w.get("mediaIds") or []
        elif w.get("mediaId"):
            mids = [w.get("mediaId")]
        # normalize & add to map
        for mid in mids:
            try:
                mid_int = int(mid)
            except Exception:
                continue
            widget_map.setdefault(mid_int, []).append(int(wid))

    # 3) If we found widget mappings, remove widgets that reference old_media_ids
    if widget_map:
        notes.append(f"Discovered widgets for playlist {playlist_id}: {widget_map}")
        for mid in old_media_ids or []:
            try:
                mid_int = int(mid)
            except Exception:
                notes.append(f"Skipping invalid media id: {mid}")
                continue
            wids = widget_map.get(mid_int, [])
            if not wids:
                notes.append(f"No widget found for mediaId {mid_int} in discovered mapping")
                continue
            for wid in wids:
                try:
                    dr = session.delete(f"{base_url}/playlist/widget/{wid}", timeout=timeout)
                except requests.exceptions.RequestException as e:
                    notes.append(f"Request error deleting widget {wid}: {e}")
                    continue
                if dr.status_code in (200, 204):
                    deleted.append((mid_int, wid))
                    notes.append(f"Deleted widget {wid} for media {mid_int}")
                else:
                    notes.append(f"Failed to delete widget {wid} (media {mid_int}): {dr.status_code} {dr.text}")

        # 4) Assign new media (creates widgets for them)
        assigned = None
        if new_media_ids:
            try:
                ar = session.post(
                    f"{base_url}/playlist/library/assign/{playlist_id}",
                    json={"media": new_media_ids},
                    timeout=timeout
                )
                ar.raise_for_status()
                assigned = ar.json()
                notes.append(f"Assigned new media to playlist {playlist_id}")
            except requests.exceptions.RequestException as e:
                notes.append(f"Failed to assign new media: {e}")
                # return what we did so far
                return {"deleted": deleted, "assigned": None, "notes": notes}
        return {"deleted": deleted, "assigned": assigned, "notes": notes}

    # 5) No widgets discovered: create widgets by assigning media directly
    notes.append(f"No widgets discovered for playlist {playlist_id}; creating widgets by assigning media.")
    if not new_media_ids:
        notes.append("No new_media_ids provided; nothing to assign.")
        return {"deleted": deleted, "assigned": None, "notes": notes}

    try:
        ar = session.post(
            f"{base_url}/playlist/library/assign/{playlist_id}",
            json={"media": new_media_ids},
            timeout=timeout
        )
        ar.raise_for_status()
        assigned = ar.json()
        notes.append(f"Assigned new media to playlist {playlist_id} (created widgets).")
        return {"deleted": deleted, "assigned": assigned, "notes": notes}
    except requests.exceptions.RequestException as e:
        notes.append(f"Failed to assign new media: {e}")
        return {"deleted": deleted, "assigned": None, "notes": notes}



def find_media_ids_for_names(base_url, headers, filenames, timeout=10):
    """
    Given a list of file names (exact file names as they appear in Xibo library),
    try to find their mediaId(s) in the CMS library.
    Returns dict: { filename: [mediaId, ...], ... }
    Notes:
      - Tries a couple of library search params (fileName, name, search) because
        installs / versions behave slightly differently.
      - base_url should be the API root (e.g. "http://mcsxibo01/api" or "https://cms.example.com/api")
    """
    session = requests.Session()
    session.headers.update(headers)
    result = {}
    for name in filenames:
        result[name] = []
        # Try a few plausible query params (order chosen by what's commonly supported)
        tried = [
            {"fileName": name},
            {"name": name},
            {"search": name},
        ]
        for params in tried:
            try:
                r = session.get(f"{base_url}/library", params=params, timeout=timeout)
                if r.status_code != 200:
                    continue
                data = r.json()
            except Exception:
                continue
            # data should be a list of library items
            for item in data:
                mid = item.get("mediaId") or item.get("media_id") or item.get("id")
                # best-effort equality check; tweak if your CMS stores slightly different fields
                if not mid:
                    continue
                # match on fileName or name or fileName substring
                if item.get("fileName") == name or item.get("name") == name or name in (item.get("fileName") or ""):
                    result[name].append(int(mid))
            if result[name]:
                break

    return result