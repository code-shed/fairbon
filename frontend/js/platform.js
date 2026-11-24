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

    /** Take a photo with the rear camera; falls back to the file picker. */
    captureReceipt: function () {
      var devices = global.navigator && global.navigator.mediaDevices;
      if (!devices || !devices.getUserMedia || !global.isSecureContext) {
        return NS.platform.pickImage();
      }

      return new Promise(function (resolve) {
        var stream = null;
        var timer = null;
        var finished = false;

        var overlay = document.createElement("div");
        overlay.className = "camera-overlay";
        overlay.setAttribute("role", "dialog");
        overlay.setAttribute("aria-label", "Kassenbon fotografieren");

        var video = document.createElement("video");
        video.autoplay = true;
        video.muted = true;
        video.setAttribute("playsinline", "");

        var frame = document.createElement("div");
        frame.className = "camera-frame";

        var hint = document.createElement("p");
        hint.className = "camera-hint";
        hint.setAttribute("role", "status");
        hint.textContent = "Kamera wird gestartet …";

        var cancel = document.createElement("button");
        cancel.type = "button";
        cancel.className = "camera-cancel";
        cancel.textContent = "Abbrechen";

        var gallery = document.createElement("button");
        gallery.type = "button";
        gallery.className = "camera-gallery";
        gallery.setAttribute("aria-label", "Foto aus der Galerie wählen");
        gallery.textContent = "Galerie";

        var shutter = document.createElement("button");
        shutter.type = "button";
        shutter.className = "camera-shutter";
        shutter.setAttribute("aria-label", "Foto aufnehmen");
        shutter.textContent = "Foto machen";

        function cleanup() {
          if (timer) { global.clearInterval(timer); timer = null; }
          if (stream) {
            stream.getTracks().forEach(function (track) { track.stop(); });
            stream = null;
          }
          if (overlay.parentNode) { document.body.removeChild(overlay); }
        }

        function finish(file) {
          if (finished) { return; }
          finished = true;
          cleanup();
          resolve(file);
        }

        function guide() {
          if (!video.videoWidth) { return; }
          var sample = document.createElement("canvas");
          sample.width = 32;
          sample.height = 32;
          var ctx = sample.getContext("2d");
          try {
            ctx.drawImage(video, 0, 0, 32, 32);
            var data = ctx.getImageData(6, 6, 20, 20).data;
            var bright = 0;
            for (var i = 0; i < data.length; i += 4) {
              var luma = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
              if (luma > 135) { bright += 1; }
            }
            var share = bright / (data.length / 4);
            hint.textContent = share < 0.35
              ? "Näher ranhalten – der Bon füllt den Rahmen noch nicht."
              : share > 0.92
                ? "Etwas weniger Licht / Blendung vermeiden."
                : "Gut – Bon im Rahmen. Jetzt fotografieren.";
          } catch (e) { /* guidance is best effort */ }
        }

        function fallbackToPicker() {
          if (finished) { return; }
          finished = true;
          cleanup();
          NS.platform.pickImage().then(resolve);
        }

        function take() {
          if (!video.videoWidth) { return; }
          var width = video.videoWidth;
          var height = video.videoHeight;
          var scale = Math.min(1, 1920 / Math.max(width, height));
          var canvas = document.createElement("canvas");
          canvas.width = Math.round(width * scale);
          canvas.height = Math.round(height * scale);
          canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
          canvas.toBlob(function (blob) {
            finish(blob ? new File([blob], "receipt-camera.jpg", {
              type: "image/jpeg"
            }) : null);
          }, "image/jpeg", 0.9);
        }

        cancel.addEventListener("click", function () { finish(null); });
        gallery.addEventListener("click", fallbackToPicker);
        shutter.addEventListener("click", take);
        overlay.addEventListener("click", function (event) {
          if (event.target === overlay) { finish(null); }
        });

        overlay.appendChild(video);
        overlay.appendChild(frame);
        overlay.appendChild(hint);
        overlay.appendChild(cancel);
        overlay.appendChild(gallery);
        overlay.appendChild(shutter);
        document.body.appendChild(overlay);

        devices.getUserMedia({
          video: {
            facingMode: { ideal: "environment" },
            width: { ideal: 1920 },
            height: { ideal: 1080 }
          },
          audio: false
        }).then(function (mediaStream) {
          stream = mediaStream;
          video.srcObject = stream;
          return video.play();
        }).then(function () {
          hint.textContent = "Bon vollständig in den Rahmen legen.";
          timer = global.setInterval(guide, 700);
        }).catch(function () {
          // Permission denied / no camera: use the plain file picker.
          fallbackToPicker();
        });
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
    askEan: function (reason) {
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
        hint.textContent = reason === "unsupported"
          ? "Dieser Browser kann Barcodes nicht per Kamera lesen – " +
            "gib die EAN unter der Verpackung ein."
          : "EAN unter der Verpackung eingeben.";
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

    /** Scan a barcode with the camera; manual EAN entry stays available. */
    scanBarcode: function () {
      var Detector = global.BarcodeDetector;
      var devices = global.navigator && global.navigator.mediaDevices;
      if (!Detector || !devices || !devices.getUserMedia || !global.isSecureContext) {
        return NS.platform.askEan("unsupported");
      }

      return new Promise(function (resolve) {
        var stream = null;
        var timer = null;
        var finished = false;
        var detector = new Detector({
          formats: ["ean_13", "ean_8", "upc_a", "code_128"]
        });

        var overlay = document.createElement("div");
        overlay.className = "camera-overlay";
        overlay.setAttribute("role", "dialog");
        overlay.setAttribute("aria-label", "Barcode scannen");

        var video = document.createElement("video");
        video.autoplay = true;
        video.muted = true;
        video.setAttribute("playsinline", "");
        var frame = document.createElement("div");
        frame.className = "camera-frame barcode-frame";
        var hint = document.createElement("p");
        hint.className = "camera-hint";
        hint.setAttribute("role", "status");
        hint.textContent = "Kamera wird gestartet …";
        var manual = document.createElement("button");
        manual.type = "button";
        manual.className = "camera-manual";
        manual.textContent = "EAN manuell eingeben";
        var cancel = document.createElement("button");
        cancel.type = "button";
        cancel.className = "camera-cancel";
        cancel.textContent = "Fertig";

        function cleanup() {
          if (timer) { global.clearInterval(timer); timer = null; }
          if (stream) {
            stream.getTracks().forEach(function (track) { track.stop(); });
            stream = null;
          }
          if (overlay.parentNode) { document.body.removeChild(overlay); }
        }
        function finish(value) {
          if (finished) { return; }
          finished = true;
          cleanup();
          resolve(value);
        }
        function manualEntry() {
          if (finished) { return; }
          finished = true;
          cleanup();
          NS.platform.askEan().then(resolve);
        }

        manual.addEventListener("click", manualEntry);
        cancel.addEventListener("click", function () { finish(null); });
        overlay.addEventListener("click", function (event) {
          if (event.target === overlay) { finish(null); }
        });
        overlay.appendChild(video);
        overlay.appendChild(frame);
        overlay.appendChild(hint);
        overlay.appendChild(manual);
        overlay.appendChild(cancel);
        document.body.appendChild(overlay);

        devices.getUserMedia({
          video: { facingMode: { ideal: "environment" } },
          audio: false
        }).then(function (mediaStream) {
          stream = mediaStream;
          video.srcObject = stream;
          return video.play();
        }).then(function () {
          hint.textContent = "Barcode in den Rahmen halten.";
          timer = global.setInterval(function () {
            if (!video.videoWidth) { return; }
            detector.detect(video).then(function (codes) {
              if (codes && codes.length) {
                if (NS.haptic) { NS.haptic(); }
                finish(String(codes[0].rawValue));
              }
            }).catch(function () { /* keep scanning */ });
          }, 350);
        }).catch(function () { manualEntry(); });
      });
    }
  };
})(window);
