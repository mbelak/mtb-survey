using Toybox.Activity;
using Toybox.ActivityRecording;
using Toybox.Attention;
using Toybox.FitContributor;
using Toybox.Graphics;
using Toybox.Math;
using Toybox.Position;
using Toybox.Sensor;
using Toybox.Timer;
using Toybox.WatchUi;

// Main view and app state.
//
// State:
//   _scale       current mtb:scale value (0-6). Changed ONLY by UP/DOWN.
//   _session     ActivityRecording session (null = no activity created).
//   _scaleField  FIT developer field "mtb_scale" on MESG_TYPE_RECORD.
//   _gpsQuality  last known Position.QUALITY_* value.
//
// Writing the developer field:
//   Field.setData() only "queues" the value for the next record the system
//   writes. For mtb_scale to be a persistent state on EVERY record, _scale is
//   therefore written to the field again once per second (onTick) and on
//   every position event (onPosition) while recording is in progress.
//   UP/DOWN only change _scale (and write the new value immediately).
//
// Motion sensors (v0.3):
//   The accelerometer and gyroscope are read at SAMPLE_HZ, in batches of one second.
//   Each batch becomes three developer fields on the record:
//     roughness  RMS of |a| around the mean for the second, mG. Shaking from roots/rocks.
//     jolt       largest deviation of |a| during the second, mG. Single hard jolts.
//     steer      RMS of the rotation rate around the vertical axis, after subtracting
//                the mean for the second, degrees/s. Small quick steering corrections, not curves.
//   The vertical axis is taken from the accelerometer's mean vector (gravity), so the values
//   do not depend on whether the watch is on the handlebar or on the wrist.
class MtbSurveyView extends WatchUi.View {
    const SCALE_MIN = 0;
    const SCALE_MAX = 6;
    const FIELD_ID_MTB_SCALE = 0;
    const FIELD_ID_ROUGHNESS = 1;
    const FIELD_ID_JOLT = 2;
    const FIELD_ID_STEER = 3;
    const TICK_MS = 1000;
    const SAMPLE_HZ = 25;
    const SENSOR_STALE_S = 3;   // sensor values older than this are not written

    var _scale = 1;
    var _session = null;
    var _scaleField = null;
    var _gpsQuality = Position.QUALITY_NOT_AVAILABLE;
    var _gpsEnabled = false;
    var _timer = null;

    var _roughField = null;
    var _joltField = null;
    var _steerField = null;
    var _sensorsOn = false;
    var _hasGyro = false;
    var _rough = null;       // latest values, null = no data
    var _jolt = null;
    var _steer = null;
    var _sensorAge = 0;      // seconds since the latest batch

    function initialize() { View.initialize(); }

    // ---- Lifecycle -------------------------------------------------------

    function onShow() {
        startGps();
        startSensors();
        if (_timer == null) {
            _timer = new Timer.Timer();
            _timer.start(method(:onTick), TICK_MS, true);
        }
    }

    // Turns everything off. Called from AppBase.onStop(). A session that
    // still exists is saved so that no track is lost.
    function shutdown() {
        if (_timer != null) { _timer.stop(); _timer = null; }
        finishSession();
        stopSensors();
        stopGps();
    }

    // ---- GPS -------------------------------------------------------------

    // Explicitly turns on continuous positioning. GPS stays on for the whole
    // lifetime of the app, that is before start, while recording and when paused.
    function startGps() {
        if (_gpsEnabled) { return; }
        Position.enableLocationEvents(Position.LOCATION_CONTINUOUS, method(:onPosition));
        _gpsEnabled = true;
    }

    function stopGps() {
        if (!_gpsEnabled) { return; }
        Position.enableLocationEvents(Position.LOCATION_DISABLE, null);
        _gpsEnabled = false;
    }

    function onPosition(info as Position.Info) as Void {
        setGpsQuality(info.accuracy);
        writeScale();
    }

    function setGpsQuality(q) {
        if (q == null) { q = Position.QUALITY_NOT_AVAILABLE; }
        if (q != _gpsQuality) {
            _gpsQuality = q;
            WatchUi.requestUpdate();
        }
    }

    // true when there is a real, current fix (not just "last known").
    function hasGpsFix() {
        return _gpsQuality >= Position.QUALITY_POOR;
    }

    // ---- Motion sensors ---------------------------------------------------

    function startSensors() {
        if (_sensorsOn) { return; }
        // Heart rate from the watch, plus ANT+ cadence/speed if such sensors are paired.
        Sensor.setEnabledSensors([Sensor.SENSOR_ONBOARD_HEARTRATE, Sensor.SENSOR_HEARTRATE,
                                  Sensor.SENSOR_BIKECADENCE, Sensor.SENSOR_BIKESPEED]);
        var acc = { :enabled => true, :sampleRate => SAMPLE_HZ };
        var gyr = { :enabled => true, :sampleRate => SAMPLE_HZ };
        try {
            Sensor.registerSensorDataListener(method(:onSensorData),
                { :period => 1, :accelerometer => acc, :gyroscope => gyr });
            _hasGyro = true;
            _sensorsOn = true;
        } catch (e) {
            // Without a gyroscope: shaking only.
            try {
                Sensor.registerSensorDataListener(method(:onSensorData),
                    { :period => 1, :accelerometer => acc });
                _sensorsOn = true;
            } catch (e2) {
                _sensorsOn = false;
            }
        }
    }

    function stopSensors() {
        if (!_sensorsOn) { return; }
        Sensor.unregisterSensorDataListener();
        _sensorsOn = false;
    }

    function onSensorData(data as Sensor.SensorData) as Void {
        var a = data.accelerometerData;
        if (a == null || a.x == null || a.x.size() < 2) { return; }
        var g = (data has :gyroscopeData) ? data.gyroscopeData : null;
        var r = (g != null && g.x != null)
            ? motionMetrics(a.x, a.y, a.z, g.x, g.y, g.z)
            : motionMetrics(a.x, a.y, a.z, null, null, null);
        _rough = r[0];
        _jolt = r[1];
        _steer = r[2];
        _sensorAge = 0;
        writeSensors();
    }

    // Writes the latest sensor values to the developer fields, like writeScale().
    function writeSensors() {
        if (_session == null || !_session.isRecording() || _sensorAge > SENSOR_STALE_S) { return; }
        if (_roughField != null && _rough != null) { _roughField.setData(_rough); }
        if (_joltField != null && _jolt != null) { _joltField.setData(_jolt); }
        if (_steerField != null && _steer != null) { _steerField.setData(_steer); }
    }

    // ---- 1 Hz-tick ---------------------------------------------------------

    function onTick() as Void {
        // Also polls the quality, in case position events stop arriving when
        // reception is lost. The status should then fall back to WAIT GPS.
        var info = Position.getInfo();
        if (info != null) { setGpsQuality(info.accuracy); }
        writeScale();
        _sensorAge += 1;
        writeSensors();
        if (_session != null && _session.isRecording()) { WatchUi.requestUpdate(); }
    }

    // Writes the current state to the developer field. Called in step
    // with the FIT records (1 Hz + position events), not only on button presses.
    function writeScale() {
        if (_scaleField != null && _session != null && _session.isRecording()) {
            _scaleField.setData(_scale);
        }
    }

    // ---- Button actions ----------------------------------------------------

    function changeScale(delta) {
        var n = _scale + delta;
        if (n < SCALE_MIN) { n = SCALE_MIN; }
        if (n > SCALE_MAX) { n = SCALE_MAX; }
        if (n == _scale) { return; }
        _scale = n;
        writeScale();
        vibrate(50, 120);
        WatchUi.requestUpdate();
    }

    function toggleRecording() {
        if (_session == null) {
            // START: create the session and developer fields, start recording.
            _session = ActivityRecording.createSession({
                :name => "MTB Survey",
                :sport => Activity.SPORT_CYCLING,
                :subSport => Activity.SUB_SPORT_MOUNTAIN
            });
            _scaleField = _session.createField("mtb_scale", FIELD_ID_MTB_SCALE,
                FitContributor.DATA_TYPE_UINT8,
                { :mesgType => FitContributor.MESG_TYPE_RECORD, :units => "grade" });
            _scaleField.setData(_scale);
            _roughField = _session.createField("roughness", FIELD_ID_ROUGHNESS,
                FitContributor.DATA_TYPE_FLOAT,
                { :mesgType => FitContributor.MESG_TYPE_RECORD, :units => "mG" });
            _joltField = _session.createField("jolt", FIELD_ID_JOLT,
                FitContributor.DATA_TYPE_FLOAT,
                { :mesgType => FitContributor.MESG_TYPE_RECORD, :units => "mG" });
            if (_hasGyro) {
                _steerField = _session.createField("steer", FIELD_ID_STEER,
                    FitContributor.DATA_TYPE_FLOAT,
                    { :mesgType => FitContributor.MESG_TYPE_RECORD, :units => "deg/s" });
            }
            _session.start();
            writeSensors();
            vibrate(100, 300);
        } else if (_session.isRecording()) {
            // PAUSE
            _session.stop();
            vibrate(60, 150);
        } else {
            // RESUME: write the value immediately so the first record after the pause is correct.
            _session.start();
            writeScale();
            vibrate(100, 300);
        }
        WatchUi.requestUpdate();
    }

    // STOP: stop, save the FIT activity and exit the app.
    function saveAndExit() {
        if (_session != null) { vibrate(100, 500); }
        finishSession();
        WatchUi.popView(WatchUi.SLIDE_IMMEDIATE);
    }

    function finishSession() {
        if (_session == null) { return; }
        if (_session.isRecording()) { _session.stop(); }
        _session.save();
        _session = null;
        _scaleField = null;
        _roughField = null;
        _joltField = null;
        _steerField = null;
    }

    function vibrate(duty, ms) {
        if (Attention has :vibrate) {
            Attention.vibrate([new Attention.VibeProfile(duty, ms)]);
        }
    }

    // ---- Rendering ---------------------------------------------------------

    function onUpdate(dc) {
        var w = dc.getWidth();
        var h = dc.getHeight();
        var cx = w / 2;

        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_BLACK);
        dc.clear();

        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, h * 7 / 100, Graphics.FONT_SMALL, "MTB SURVEY", Graphics.TEXT_JUSTIFY_CENTER);

        // GPS status: always visible, also while recording.
        var gpsText = "WAIT GPS";
        var gpsColor = Graphics.COLOR_RED;
        if (_gpsQuality >= Position.QUALITY_USABLE) {
            gpsText = "GPS OK";
            gpsColor = Graphics.COLOR_GREEN;
        } else if (_gpsQuality == Position.QUALITY_POOR) {
            gpsText = "GPS POOR";
            gpsColor = Graphics.COLOR_YELLOW;
        }
        dc.setColor(gpsColor, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, h * 17 / 100, Graphics.FONT_MEDIUM, gpsText, Graphics.TEXT_JUSTIFY_CENTER);

        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, h * 44 / 100, Graphics.FONT_NUMBER_HOT, _scale.format("%d"),
            Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);
        dc.drawText(cx, h * 59 / 100, Graphics.FONT_SMALL, "mtb:scale", Graphics.TEXT_JUSTIFY_CENTER);

        var recText = "START = record";
        var recColor = Graphics.COLOR_LT_GRAY;
        if (_session != null) {
            if (_session.isRecording()) {
                recText = "RECORDING";
                recColor = Graphics.COLOR_GREEN;
            } else {
                recText = "PAUSED";
                recColor = Graphics.COLOR_YELLOW;
            }
        }
        dc.setColor(recColor, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, h * 71 / 100, Graphics.FONT_SMALL, recText, Graphics.TEXT_JUSTIFY_CENTER);

        // While recording: live sensor values, so you can see that they are coming in.
        var hint = "UP harder  DOWN easier";
        if (_session != null && _session.isRecording()) {
            if (_rough == null || _sensorAge > SENSOR_STALE_S) {
                hint = "NO MOTION DATA";
            } else {
                hint = "RGH " + _rough.format("%d") +
                       (_steer != null ? "  STR " + _steer.format("%d") : "");
            }
        }
        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, h * 83 / 100, Graphics.FONT_XTINY, hint, Graphics.TEXT_JUSTIFY_CENTER);
    }
}

// Pure calculation, independent of the sensor API so that it can be unit tested.
// ax/ay/az in mG, wx/wy/wz in degrees/s (null = no gyroscope).
// Returns [roughness, jolt, steer]; steer is null without a gyroscope.
function motionMetrics(ax, ay, az, wx, wy, wz) {
    var n = ax.size();
    var gx = 0.0, gy = 0.0, gz = 0.0, mean = 0.0;
    var mag = new [n];
    for (var i = 0; i < n; i++) {
        var x = ax[i].toFloat(), y = ay[i].toFloat(), z = az[i].toFloat();
        gx += x; gy += y; gz += z;
        mag[i] = Math.sqrt(x * x + y * y + z * z);
        mean += mag[i];
    }
    mean /= n; gx /= n; gy /= n; gz /= n;
    var ss = 0.0, peak = 0.0;
    for (var i = 0; i < n; i++) {
        var d = (mag[i] - mean).abs();
        ss += d * d;
        if (d > peak) { peak = d; }
    }
    var steer = null;
    var gn = Math.sqrt(gx * gx + gy * gy + gz * gz);
    if (wx != null && wx.size() > 1 && gn > 100.0) {
        var m = wx.size();
        var yaw = new [m];
        var ym = 0.0;
        for (var i = 0; i < m; i++) {
            // rotation around the direction of gravity = steering movement
            yaw[i] = (wx[i] * gx + wy[i] * gy + wz[i] * gz) / gn;
            ym += yaw[i];
        }
        ym /= m;
        var ys = 0.0;
        for (var i = 0; i < m; i++) { ys += (yaw[i] - ym) * (yaw[i] - ym); }
        steer = Math.sqrt(ys / m);
    }
    return [Math.sqrt(ss / n), peak, steer];
}
