#!/usr/bin/env python3

import datetime
import pathlib
import threading
import zipfile
from contextlib import closing

import arrow
import bottle
import bottle_peewee
import cachetools as cachetools
import functools
import os
import peewee as pw
import re
import requests

DOMAIN = "http://app.pr0gramm.com"

# create and install database plugin
db = bottle_peewee.PeeweePlugin("sqlite:///apks/_updates.db")
bottle.install(db)


class Version(pw.Model):
    version = pw.PrimaryKeyField(unique=True, db_column='id')
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


# create table for database plugin
db.database.create_tables([Version], safe=True)

# we just keep this in memory
info_message_string = None

# create apk folder
apk_root = pathlib.Path("apks")
if not apk_root.exists():
    apk_root.mkdir()


def format_version(version):
    if isinstance(version, Version):
        version = version.version

    major, minor, path = (version // 1000) + 1, version // 10, version % 10
    return "{}.{}.{}".format(major, minor, path)


def github_url_for_version(version):
    if isinstance(version, Version):
        version = version.version

    major, minor, path = (version // 1000), version // 10, version % 10
    return "https://github.com/mopsalarm/Pr0/releases/download/{}.{}.{}/app-release.apk".format(major, minor, path)


def jinja_filters():
    def version_format(version):
        return format_version(version)

    def humanize(date):
        date = arrow.get(date, tz="utc")
        return date.humanize()

    return locals()


template_settings = {"filters": jinja_filters()}
render_view = functools.partial(bottle.jinja2_view,
                                template_settings=template_settings)


@bottle.get("/update-manager/")
@render_view("templates/index.html.j2")
def req_index():
    versions = list(Version.select().order_by(Version.version.desc()).limit(16))
    most_recent_version = next((v.version for v in versions), 0)

    return {
        "versions": versions,
        "info_message": info_message_string,
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


@bottle.post("/update-manager/info-message")
def req_set_info_message():
    global info_message_string
    info_message_string = bottle.request.forms.getunicode("message")
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
    version = Version.get(*query)

    # url = github_url_for_version(version)
    # if not validate_apk_url(url):
    # url = "{}/apk/{}/{}".format("http://pr0-app.wibbly-wobbly.de", version.version, version.filename)
    url = "https://apk.pr0gramm.com/" + version.filename

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
        version_code = extract_version_code(upload_file)

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


def extract_version_code(fp):
    version_file = "assets/crashlytics-build.properties"
    with zipfile.ZipFile(fp) as apk, apk.open(version_file) as props:
        match = re.search(br'version_code=([0-9]+)', props.read())
        if not match:
            raise IOError("Could not find version in upload")

        return int(match.group(1))


@bottle.get("/update-manager/static/<path:path>")
def req_static(path):
    root = pathlib.Path(__file__).parent / "static"
    return bottle.static_file(path, str(root))


# public stuff


@bottle.get("/beta/update.json")
def req_beta_update_json():
    return update_json(Version.beta)


@bottle.get("/stable/update.json")
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
    # get static message
    info_message = info_message_string

    version = extract_version_from_request(bottle.request)
    if version is not None:
        version = version // 10
        newest_version = Version.get(stable=True).version // 10
        if version <= newest_version - 2:
            if info_message:
                info_message += ". Warum updatest du die App nicht? Gib doch mal bitte Feedback."
            else:
                info_message = "ACHTUNG: Deine Version ist ziemlich alt. " \
                               "Gehe bitte unbedingt updaten, da deine Version sonst bald nicht mehr unterstützt wird! " \
                               "Zusätzlich gibt es viele Bugfixes und neue Features! Falls dir was am Herzen liegt, gib doch bitte Feedback."

    bottle.response.set_header("Vary", "User-Agent")
    return {"message": info_message, "endOfLife": 1369}


def extract_version_from_request(request):
    agent = request.get_header("User-Agent", "")
    match = re.match(r"pr0gramm-app/v([0-9]+)", agent)
    if match is None:
        return None

    return int(match.group(1))
