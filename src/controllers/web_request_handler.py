from json import JSONDecodeError

from src.devicemanagement.constants import Version

# ``requests`` (and its urllib3/certifi tree) costs ~100 ms to import and is
# only needed when an update check actually runs, so it is pulled in lazily
# inside get_latest_version() instead of at module import. This module sits on
# the GUI startup import graph (dialogs -> icon pack downloader).

Nugget_Repo = "GoldenNugget-Team/GoldenNugget/releases/latest"

last_fetched_version: str = None
last_fetched_release: dict = {}
# True when the last fetch failed (network, rate limit, timeout, bad JSON).
# A 404 (no releases) leaves this False so callers can keep treating it as
# "no update".
_update_check_failed: bool = False

def is_update_available(version: str, build: int):
    """True when a newer release exists, False when current, None when the check failed.

    A GitHub 404 (no releases published) is False, same as "already current".
    """
    # check github for if version < tag (or == tag but build > 0)
    latest_version = get_latest_version()
    if latest_version is None:
        return None if _update_check_failed else False
    if build > 0 and latest_version == version: # on beta version when there is a public release
        return True
    if Version(latest_version) > Version(version):
        return True
    return False

def get_latest_version() -> str:
    global last_fetched_version, last_fetched_release, _update_check_failed
    # get the cached version
    if last_fetched_version != None:
        return last_fetched_version
    # Lazy import: see the module header.
    from requests import HTTPError, RequestException, get
    # fetch with web requests
    try:
        response = get(f"https://api.github.com/repos/{Nugget_Repo}", timeout=5)
        response.raise_for_status()  # To raise an exception for 4xx/5xx responses

        data = response.json()  # Parse the JSON response
        if not isinstance(data, dict):
            _update_check_failed = True
            return None
        last_fetched_release = data

        # Check if "tag_name" exists in the response and compare the version
        tag_name = data.get("tag_name")
        if tag_name:
            last_fetched_version = tag_name.replace("v", "")  # Remove 'v' from tag_name
            _update_check_failed = False
            return last_fetched_version
        # 200 with no tag is "no release to compare", not a failed check.
        _update_check_failed = False
    except HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            # no releases published yet — not a real error
            _update_check_failed = False
            return None
        _update_check_failed = True
        print(f"Error fetching data: {e}")
    except RequestException as e:
        _update_check_failed = True
        print(f"Error fetching data: {e}")
    except JSONDecodeError as e:
        _update_check_failed = True
        print(f"Error parsing JSON: {e}")
    return None
def update_download_url():
    import platform
    import sys
    from urllib.parse import quote, urlparse
    suffixes = ('.dmg', '.zip') if sys.platform == 'darwin' else ('.exe', '.msi', '.zip') if sys.platform == 'win32' else ('.appimage', '.tar.gz')
    assets = last_fetched_release.get('assets', [])
    for suffix in suffixes:
        for asset in assets if isinstance(assets, list) else []:
            if not isinstance(asset, dict):
                continue
            name = str(asset.get('name', '')).lower()
            url = asset.get('browser_download_url', '')
            platform_words = ('mac', 'darwin', 'osx') if sys.platform == 'darwin' else ('win', 'windows') if sys.platform == 'win32' else ('linux', 'appimage')
            arm = platform.machine().lower() in ('arm64', 'aarch64')
            if (not arm and any(word in name for word in ('arm64', 'aarch64'))
                    or arm and any(word in name for word in ('x86_64', 'x64', 'amd64', 'intel'))):
                continue
            if name.endswith(suffix) and (suffix in ('.dmg', '.exe', '.msi', '.appimage') or any(word in name for word in platform_words)):
                if isinstance(url, str) and urlparse(url).scheme == 'https' and urlparse(url).hostname == 'github.com' and urlparse(url).path.startswith('/GoldenNugget-Team/GoldenNugget/releases/download/'):
                    return url
    tag = last_fetched_release.get('tag_name')
    if isinstance(tag, str) and tag:
        return 'https://github.com/GoldenNugget-Team/GoldenNugget/archive/refs/tags/' + quote(tag, safe='') + '.zip'
    return 'https://github.com/GoldenNugget-Team/GoldenNugget/releases/latest'
