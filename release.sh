#!/usr/bin/fish

if [ (count $argv) -ne 2 ]
  echo "usage: "(status -f)" version changelog"
  exit 1
end

set p_version $argv[1]
set p_changelog $argv[2]

function generate_update_json
  set flavor $argv[1]
  set url https://cdn.rawgit.com/mopsalarm/pr0gramm-updates/beta/$flavor/pr0gramm-v1.$p_version.apk

  echo "{}" \
    | jq '.version = '$p_version \
    | jq '.versionStr = "1.'(math $p_version/10)'.'(math $p_version%10)'"' \
    | jq '.changelog = "'$p_changelog'"' \
    | jq '.apk = "'$url'"' > $flavor/update.json

  git add $flavor/update.json
end

function copy_apk_file
  set flavor $argv[1]
  cp ../pr0gramm/app/build/outputs/apk/app-$flavor-release.apk $flavor/pr0gramm-v1.$p_version.apk
  git add $flavor/pr0gramm-v1.$p_version.apk
end

for flavor in open play
  copy_apk_file $flavor
  generate_update_json $flavor
end

# fallback for very old apps
cp open/update.json update.json
git add update.json

# print the update json to verify everything is okay
jq . < update.json
