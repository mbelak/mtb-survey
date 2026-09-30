using Toybox.Application;
using Toybox.WatchUi;

class MtbSurveyApp extends Application.AppBase {
    var _view = null;

    function initialize() { AppBase.initialize(); }

    function getInitialView() {
        _view = new MtbSurveyView();
        return [ _view, new MtbSurveyDelegate(_view) ];
    }

    // Anropas när appen avslutas, oavsett väg ut. Ser till att en pågående
    // inspelning sparas och att GPS och timer stängs av.
    function onStop(state) {
        if (_view != null) { _view.shutdown(); }
    }
}
