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
    compressImage: function (file, maxWidth, quality, enhance) {
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
            var factor = enhance === true ? 1.5 : 1.15;
            var source = enhance === true ? data.slice() : null;
            for (var i = 0; i < data.length; i += 4) {
              var gray = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
              gray = Math.max(0, Math.min(255, (gray - 128) * factor + 128));
              if (source) {
                // Light unsharp mask for faded thermal-paper prints.
                var sharp = gray * 1.18 -
                  0.09 * (source[i - 4] || source[i]) -
                  0.09 * (source[i + 4] || source[i]);
                gray = Math.max(0, Math.min(255, sharp));
              }
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
    },

    /** Ask for an EAN when no BarcodeDetector is available (or detection fails). */
    askEan: function () {
      return new Promise(function (resolve) {
        var backdrop = document.createElement("div");
        backdrop.className = "modal-backdrop";
        var box = document.createElement("div");
        box.className = "modal modal--sheet ean-modal";
        box.setAttribute("role", "dialog");
        box.setAttribute("aria-label", "Barcode eingeben");

        var title = document.createElement("h2");
        title.textContent = "Barcode scannen";
        var hint = document.createElement("p");
        hint.className = "detail-note";
        hint.textContent = "Kamera nicht verfügbar? Gib die EAN unter der Verpackung ein.";
        var field = document.createElement("label");
        field.className = "field";
        field.textContent = "EAN / GTIN";
        var input = document.createElement("input");
        input.type = "text";
        input.inputMode = "numeric";
        input.maxLength = 14;
        input.autocomplete = "off";
        input.placeholder = "z. B. 4000400011111";
        field.appendChild(input);
        var actions = document.createElement("div");
        actions.className = "modal-actions";
        var cancel = document.createElement("button");
        cancel.type = "button";
        cancel.className = "secondary";
        cancel.textContent = "Fertig";
        var ok = document.createElement("button");
        ok.type = "button";
        ok.className = "primary";
        ok.textContent = "Übernehmen";
        var error = document.createElement("p");
        error.className = "form-error";
        error.hidden = true;

        function close(value) {
          if (backdrop.parentNode) { document.body.removeChild(backdrop); }
          if (box.parentNode) { document.body.removeChild(box); }
          resolve(value);
        }
        cancel.addEventListener("click", function () { close(null); });
        backdrop.addEventListener("click", function () { close(null); });
        ok.addEventListener("click", function () {
          var ean = input.value.replace(/\D/g, "");
          if (ean.length < 8 || ean.length > 14) {
            error.textContent = "Bitte 8 bis 14 Ziffern eingeben.";
            error.hidden = false;
            return;
          }
          close(ean);
        });
        input.addEventListener("keydown", function (event) {
          if (event.key === "Enter") { ok.click(); }
        });

        actions.appendChild(cancel);
        actions.appendChild(ok);
        box.appendChild(title);
        box.appendChild(hint);
        box.appendChild(field);
        box.appendChild(error);
        box.appendChild(actions);
        document.body.appendChild(backdrop);
        document.body.appendChild(box);
        input.focus();
      });
    },

    /** Scan one barcode; falls back to manual entry without ever rejecting. */
    scanBarcode: function () {
      var Detector = global.BarcodeDetector;
      if (!Detector) { return NS.platform.askEan(); }
      return NS.platform.pickImage().then(function (file) {
        if (!file) { return NS.platform.askEan(); }
        return NS.platform.readAsDataURL(file).then(function (src) {
          return new Promise(function (resolve) {
            var image = new Image();
            image.onload = function () {
              try {
                var detector = new Detector({
                  formats: ["ean_13", "ean_8", "upc_a", "code_128"]
                });
                detector.detect(image).then(function (codes) {
                  resolve(codes && codes.length
                    ? String(codes[0].rawValue)
                    : NS.platform.askEan());
                }).catch(function () { resolve(NS.platform.askEan()); });
              } catch (e) { resolve(NS.platform.askEan()); }
            };
            image.onerror = function () { resolve(NS.platform.askEan()); };
            image.src = src;
          });
        });
      }).catch(function () { return NS.platform.askEan(); });
    }
  };
})(window);
