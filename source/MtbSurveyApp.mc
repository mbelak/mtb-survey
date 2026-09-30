using Toybox.Application;
using Toybox.WatchUi;

class MtbSurveyApp extends Application.AppBase {
    var _view = null;

    function initialize() { AppBase.initialize(); }

    function getInitialView() {
        _view = new MtbSurveyView();
        return [ _view, new MtbSurveyDelegate(_view) ];
    }

    // Called when the app exits, whichever way. Makes sure an ongoing
    // recording is saved and that GPS and the timer are turned off.
    function onStop(state) {
        if (_view != null) { _view.shutdown(); }
    }
}
