import datetime
import functools
import json
import os
import pathlib
import re
import zipfile
from contextlib import closing

import arrow
import bottle
import bottle_peewee
import peewee as pw

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


class Config(pw.Model):
    version = pw.PrimaryKeyField(unique=True, db_column="id")
    json = pw.TextField(default="{}")

    class Meta(object):
        database = db.proxy


# create table for database plugin
db.database.create_tables([Version, Config], safe=True)

# create the default config value
Config.get_or_create(version=0)

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
    versions = list(Version.select().order_by(Version.version.desc()))
    base_config = json.dumps(config_get(version_code=0), indent=2, sort_keys=True)
    return {
        "versions": versions,
        "info_message": info_message_string,
        "base_config": base_config
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


@bottle.get("/app-config/<version_code:int>/config.json")
def config_get(version_code):
    config = json.loads(Config.get(version=0).json)

    # mix in more specific config
    for specific in Config.select().where(Config.version == version_code):
        config.update(json.loads(specific.json))

    return config


@bottle.post("/update-manager/app-config")
def update_base_config():
    parsed = json.loads(bottle.request.forms["json"])
    Config(version=0, json=json.dumps(parsed)).save()
    return bottle.redirect("/update-manager/#base-config")


def update_json(*query):
    version = Version.get(*query)
    return {
        "apk": "{}/apk/{}/{}".format(DOMAIN, version.version, version.filename),
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

    agent = bottle.request.get_header("User-Agent", "")
    match = re.match(r"pr0gramm-app/v([0-9]+)", agent)
    if match is not None:
        version = int(match.group(1)) // 10
        newest_version = Version.get(stable=True).version // 10
        if version <= newest_version - 2:
            if info_message:
                info_message += ", außerdem: GEH VERDAMMT NOCHMAL UPDATEN!"
            else:
                info_message = "ACHTUNG: Deine Version ist ziemlich alt. " \
                               "Gehe bitte unbedingt updaten, da deine Version sonst bald nicht mehr unterstützt wird! " \
                               "Zusätzlich gibt es viele Bugfixes und neue Features!"

    bottle.response.set_header("Vary", "User-Agent")
    return {"message": info_message}
