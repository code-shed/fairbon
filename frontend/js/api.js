/* FairBon — central API client (ES5).
   In the browser API_BASE_URL is "" (same origin); for Capacitor set it to
   the public server origin, e.g. "https://fairbon.example.org". */
(function (global) {
  "use strict";

  var NS = global.FairBon = global.FairBon || {};

  NS.API_BASE_URL = global.FAIRBON_API_BASE_URL || "";

  function headers(extra) {
    var result = { Accept: "application/json" };
    if (NS.ownerToken) { result["X-Owner-Token"] = NS.ownerToken; }
    if (NS.state && NS.state.byok) { result["X-User-Vision-Key"] = NS.state.byok; }
    if (extra) {
      for (var key in extra) {
        if (Object.prototype.hasOwnProperty.call(extra, key)) {
          result[key] = extra[key];
        }
      }
    }
    return result;
  }

  function url(path) {
    if (/^https?:\/\//.test(path)) { return path; }
    return NS.API_BASE_URL + path;
  }

  NS.api = {
    headers: headers,
    url: url,

    get: function (path, options) {
      options = options || {};
      return fetch(url(path), {
        method: "GET",
        headers: headers(options.headers)
      }).then(parse).catch(networkError);
    },

    postForm: function (path, formData, options) {
      options = options || {};
      return fetch(url(path), {
        method: "POST",
        headers: headers(options.headers),
        body: formData
      }).then(parse).catch(networkError);
    },

    postJson: function (path, payload, options) {
      options = options || {};
      var h = headers(options.headers);
      h["Content-Type"] = "application/json";
      return fetch(url(path), {
        method: "POST",
        headers: h,
        body: JSON.stringify(payload)
      }).then(parse).catch(networkError);
    },

    del: function (path, options) {
      options = options || {};
      return fetch(url(path), {
        method: "DELETE",
        headers: headers(options.headers)
      }).then(parse).catch(networkError);
    },

    patchForm: function (path, formData, options) {
      options = options || {};
      return fetch(url(path), {
        method: "PATCH",
        headers: headers(options.headers),
        body: formData
      }).then(parse).catch(networkError);
    }
  };

  function networkError(error) {
    if (error instanceof TypeError) {
      throw new Error("Keine Verbindung zum Server. Bitte später erneut versuchen.");
    }
    throw error;
  }

  function parse(response) {
    var contentType = response.headers.get("content-type") || "";
    var body = contentType.indexOf("application/json") >= 0
      ? response.json()
      : response.text();
    return body.then(function (data) {
      if (!response.ok) {
        var message = data && data.detail ? data.detail : "Anfrage fehlgeschlagen.";
        var error = new Error(message);
        error.status = response.status;
        error.data = data;
        throw error;
      }
      return data;
    });
  }
})(window);
