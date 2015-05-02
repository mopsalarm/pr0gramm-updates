function getCurrentVersion(callback) {
	var url = "https://github.com/mopsalarm/pr0gramm-updates/raw/master/update.json";
	jQuery.getJSON(url).done(function(json) {
		callback(json.apk);
	});
}

