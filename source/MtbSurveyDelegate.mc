using Toybox.WatchUi;

class MtbSurveyDelegate extends WatchUi.InputDelegate {
    var _view;
    function initialize(view) { InputDelegate.initialize(); _view = view; }

    function onKey(evt) {
        var key = evt.getKey();
        if (key == WatchUi.KEY_UP) { _view.changeScale(1); return true; }
        if (key == WatchUi.KEY_DOWN) { _view.changeScale(-1); return true; }
        if (key == WatchUi.KEY_ENTER) { _view.toggleRecording(); return true; }
        if (key == WatchUi.KEY_ESC) { _view.saveAndExit(); return true; }
        return false;
    }
}
