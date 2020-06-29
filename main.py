#!/usr/bin/env python3

import datetime
import functools
import os
import pathlib
import re
import threading
from contextlib import closing

import arrow
import bottle
import bottle_peewee
import cachetools as cachetools
import peewee as pw
import requests
from pyaxmlparser import APK

DOMAIN = "http://app.pr0gramm.com"

# create and install database plugin
db = bottle_peewee.PeeweePlugin("sqlite:///apks/_updates.db")
bottle.install(db)


class Version(pw.Model):
    version = pw.AutoField(unique=True, column_name='id')
    created = pw.DateTimeField()
    filename = pw.TextField()
    stable = pw.BooleanField(default=False)
    beta = pw.BooleanField(default=False)
    notice = pw.TextField()

    @property
    def size(self):
        try:
            return (apk_root / self.filename).stat().st_size
        except OSError:
            return -1

    class Meta(object):
        database = db.proxy


class InfoMessage(pw.Model):
    message = pw.TextField(default=None, null=True)
    message_id = pw.TextField(default=None, null=True)
    end_of_life_version = pw.IntegerField(default=None, null=True)

    class Meta(object):
        database = db.proxy


# create table for database plugin
db.database.create_tables([Version, InfoMessage], safe=True)


# create apk folder
apk_root = pathlib.Path("apks")
if not apk_root.exists():
    apk_root.mkdir()


def format_version(version: int):
    if isinstance(version, Version):
        version = version.version

    major, minor, path = (version // 1000), version // 10, version % 10
    return "{}.{}.{}".format(major, minor, path)


def jinja_filters():
    def version_format(version):
        return format_version(version)

    def humanize(date):
        date = arrow.get(date, tz="utc")
        return date.humanize()

    return locals()



template_settings = {"filters": jinja_filters()}
render_view = functools.partial(bottle.jinja2_view, template_settings=template_settings)


@bottle.get("/update-manager/")
@render_view("templates/index.html.j2")
def req_index():
    versions = list(Version.select().order_by(Version.version.desc()).limit(16))
    most_recent_version = next((v.version for v in versions), 0)

    return {
        "versions": versions,
        "info_message": get_info_message(),
        "most_recent_version": most_recent_version,
    }


@bottle.post("/update-manager/version/<version_code:int>/notice")
def req_post_notice(version_code):
    version = Version.get(version=version_code)
    version.notice = bottle.request.forms.getunicode("notice")
    version.save()
    return bottle.redirect("/update-manager/")


@bottle.get("/update-manager/version/<version_code:int>/set/stable")
def req_version_set_stable(version_code):
    Version.update(stable=False).where(Version.stable).execute()

    version = Version.get(version=version_code)
    version.stable = True
    version.save()

    return bottle.redirect("/update-manager/")


@bottle.get("/update-manager/version/<version_code:int>/set/beta")
def req_version_set_stable(version_code):
    Version.update(beta=False).where(Version.beta).execute()

    version = Version.get(version=version_code)
    version.beta = True
    version.save()

    return bottle.redirect("/update-manager/")


@bottle.get("/update-manager/version/<version_code:int>/set/eol")
def req_version_set_eol(version_code):
    info = get_info_message()

    if info.end_of_life_version == version_code:
        info.end_of_life_version = None
    else:
        info.end_of_life_version = version_code

    info.save()

    return bottle.redirect("/update-manager/")


@bottle.post("/update-manager/info-message")
def req_set_info_message():
    message = bottle.request.forms.getunicode("message")
    message_id = bottle.request.forms.getunicode("messageId")

    info = get_info_message()
    info.message = message or None
    info.message_id = message_id or None
    info.save()

    return bottle.redirect("/update-manager/")


urlcache = cachetools.TTLCache(maxsize=16, ttl=600)


@cachetools.cached(urlcache, lock=threading.RLock())
def validate_apk_url(url):
    try:
        print(url)
        resp = requests.get(url, headers={'Range': 'bytes=0-128'})
        print(resp.status_code)
        return resp.status_code == 206

    except Exception as err:
        print("Could not validate url: ", err)
        return False


def update_json(*query):
    # no more updates for old android versions. :/
    android_version = bottle.request.query.get("androidVersion")
    if android_version is not None and int(android_version) < 21:
        return {"apk": "https://example.com", "version": 0, "versionStr": "", "changelog": []}
    
    version = Version.get(*query)

    # cache on cloudflare.
    bottle.response.set_header("Cache-Control", "public, max-age=60")

    url = "{}/apk/{}/{}".format(DOMAIN, version.version, version.filename)
    return {
        "apk": url,
        "version": version.version,
        "versionStr": format_version(version),
        "changelog": version.notice
    }


@bottle.route('/update-manager/upload', method='POST')
def req_upload():
    # get the uploaded item
    upload = bottle.request.files.get('apk')
    name, ext = os.path.splitext(upload.filename)
    if ext != ".apk":
        raise IOError("File extension not allowed.")

    with closing(upload.file) as upload_file:
        # get the version_code from the zip file
        version_code = extract_apk_version_code(upload_file)

        # check if this version already exists
        if Version.filter(version=version_code).exists():
            raise IOError("Version {} already exists!".format(version_code))

        # write the apk file to disk
        upload.file.seek(0)
        target_name = "pr0gramm-{}.apk".format(format_version(version_code))
        with (apk_root / target_name).open("wb") as out:
            upload.save(out)

    # store the new entry in the database
    Version.create(version=version_code,
                   notice="Version {}".format(version_code),
                   created=datetime.datetime.utcnow(),
                   filename=target_name)

    return bottle.redirect("/update-manager/")


def extract_apk_version_code(fp):
    source = fp.read()
    return int(APK(source, raw=True).version_code)


# @bottle.get("/update-manager/static/<path:path>")
# def req_static(path):
#     root = pathlib.Path(__file__).parent / "static"
#     return bottle.static_file(path, str(root))


# public stuff


@bottle.get("/beta/update.json")
@bottle.get("/updates/beta/update.json")
def req_beta_update_json():
    return update_json(Version.beta)


@bottle.get("/stable/update.json")
@bottle.get("/updates/stable/update.json")
def req_beta_update_json():
    return update_json(Version.stable)


@bottle.get("/pr0gramm-latest.apk")
def req_apk_stable():
    version = Version.get(stable=True)
    return bottle.redirect("{}/apk/{}/{}".format(DOMAIN, version.version, version.filename))


@bottle.get("/apk/<version_code:int>/<:path>")
def req_apk(version_code):
    version = Version.get(version=version_code)
    return bottle.static_file(
        version.filename,
        root=str(apk_root),
        download=True,
        mimetype="application/vnd.android.package-archive")


@bottle.get("/info-message.json")
def req_info_message():
    info = get_info_message()
    message = info.message

    version = extract_version_from_request(bottle.request)
    if not message and version is not None:
        # check if the user uses a really old version
        if Version.get(stable=True).version - version > 20:
            message = "Die Version der App ist ziemlich alt. " \
                      "Bitte führe unbedingt ein Update durch, da diese Version bald nicht mehr unterstützt wird! " \
                      "https://app.pr0gramm.com"

    bottle.response.set_header("Vary", "User-Agent")
    bottle.response.set_header("Cache-Control", "public, max-age=60")

    message_id = "info:" + info.message_id if info.message_id else None

    return {
        "message": message,
        "messageId": message_id,
        "endOfLife": info.end_of_life_version,
    }


def extract_version_from_request(request):
    agent = request.get_header("User-Agent", default="")
    match = re.match(r"pr0gramm-app/v([0-9]+)", agent)
    return int(match.group(1)) if match else None


def get_info_message() -> InfoMessage:
    info, _ = InfoMessage.get_or_create(id=1)
    return info
