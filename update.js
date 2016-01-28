function getUpdateJson(callback) {
	var url = "https://rawgit.com/mopsalarm/pr0gramm-updates/master/open/update.json";
	jQuery.getJSON(url).done(function(json) {
		callback(json);
	});
}

function getCurrentVersion(callback) {
	getUpdateJson(function(json) {
		callback(json.apk);
	});
}
