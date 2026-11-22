/* FairBon — platform abstraction for camera/file access (ES5).

   All camera and file-picker access goes through this module so a later
   Capacitor build can swap the web file input for the native camera plugin
   in one place.  It also provides the client-side canvas compression
   (max 1200 px, grayscale, JPEG ~0.82) required by the scan pipeline. */
(function (global) {
  "use strict";

  var NS = global.FairBon = global.FairBon || {};

  var MAX_WIDTH = 1200;
  var QUALITY = 0.82;

  NS.platform = {
    /** Open the native camera/file picker and resolve with a File or null. */
    pickImage: function () {
      return new Promise(function (resolve) {
        var input = document.createElement("input");
        input.type = "file";
        input.accept = "image/*";
        input.setAttribute("capture", "environment");
        input.style.position = "fixed";
        input.style.left = "-9999px";
        document.body.appendChild(input);
        input.addEventListener("change", function () {
          var file = input.files && input.files[0] ? input.files[0] : null;
          document.body.removeChild(input);
          resolve(file);
        });
        input.click();
      });
    },

    /** Resolve a data-URL/data-URI image for previews. */
    readAsDataURL: function (file) {
      return new Promise(function (resolve, reject) {
        var reader = new FileReader();
        reader.onload = function () { resolve(reader.result); };
        reader.onerror = function () { reject(reader.error); };
        reader.readAsDataURL(file);
      });
    },

    /** Downscale + grayscale + JPEG-compress an image File in the browser. */
    compressImage: function (file, maxWidth, quality) {
      maxWidth = maxWidth || MAX_WIDTH;
      quality = quality || QUALITY;
      return new Promise(function (resolve, reject) {
        var objectUrl = global.URL.createObjectURL(file);
        var image = new Image();
        image.onload = function () {
          try {
            var scale = Math.min(1, maxWidth / image.width);
            var width = Math.max(1, Math.round(image.width * scale));
            var height = Math.max(1, Math.round(image.height * scale));
            var canvas = document.createElement("canvas");
            canvas.width = width;
            canvas.height = height;
            var ctx = canvas.getContext("2d");
            ctx.drawImage(image, 0, 0, width, height);
            // Grayscale + slight contrast for OCR/vision robustness.
            var pixels = ctx.getImageData(0, 0, width, height);
            var data = pixels.data;
            for (var i = 0; i < data.length; i += 4) {
              var gray = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
              gray = Math.max(0, Math.min(255, (gray - 128) * 1.15 + 128));
              data[i] = data[i + 1] = data[i + 2] = gray;
            }
            ctx.putImageData(pixels, 0, 0);
            canvas.toBlob(function (blob) {
              global.URL.revokeObjectURL(objectUrl);
              if (!blob) { reject(new Error("Bild konnte nicht komprimiert werden.")); return; }
              resolve(new File([blob], "receipt.jpg", { type: "image/jpeg" }));
            }, "image/jpeg", quality);
          } catch (err) {
            global.URL.revokeObjectURL(objectUrl);
            reject(err);
          }
        };
        image.onerror = function () {
          global.URL.revokeObjectURL(objectUrl);
          reject(new Error("Bild konnte nicht gelesen werden."));
        };
        image.src = objectUrl;
      });
    }
  };
})(window);
