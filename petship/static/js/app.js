/* PetShip front-end glue.
   Ensures htmx-issued non-GET requests carry the CSRF token so Flask-WTF's
   CSRFProtect accepts them. The token is read from a <meta> tag rendered in
   the base layouts. */
(function () {
  function getCsrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : null;
  }

  document.addEventListener('htmx:configRequest', function (evt) {
    var method = (evt.detail.verb || 'get').toLowerCase();
    if (method !== 'get') {
      var token = getCsrfToken();
      if (token) {
        evt.detail.headers['X-CSRFToken'] = token;
      }
    }
  });
})();
