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

// Huvudvy och appens tillstånd.
//
// Tillstånd:
//   _scale       aktuellt mtb:scale-värde (0-6). Ändras ENDAST av UP/DOWN.
//   _session     ActivityRecording-session (null = ingen aktivitet skapad).
//   _scaleField  FIT developer field "mtb_scale" på MESG_TYPE_RECORD.
//   _gpsQuality  senast kända Position.QUALITY_*-värde.
//
// Skrivning av developer field:
//   Field.setData() lägger bara värdet "i kö" till nästa record som systemet
//   skriver. För att mtb_scale ska vara ett persistent tillstånd på VARJE
//   record skrivs därför _scale om till fältet en gång per sekund (onTick)
//   samt vid varje positionshändelse (onPosition) så länge inspelning pågår.
//   UP/DOWN ändrar bara _scale (och skriver det nya värdet direkt).
//
// Rörelsesensorer (v0.3):
//   Accelerometer och gyroskop läses i SAMPLE_HZ, i paket om en sekund.
//   Varje paket blir tre developer fields på record:
//     roughness  RMS av |a| kring sekundens medel, mG. Skakningar från rötter/stenar.
//     jolt       största avvikelsen av |a| under sekunden, mG. Enstaka hårda stötar.
//     steer      RMS av vridhastigheten kring lodaxeln, efter att sekundens medel
//                dragits bort, grader/s. Små snabba styrkorrigeringar, inte kurvor.
//   Lodaxeln tas från accelerometerns medelvektor (tyngdkraften), så värdena
//   beror inte på hur klockan sitter på styret eller handleden.
class MtbSurveyView extends WatchUi.View {
    const SCALE_MIN = 0;
    const SCALE_MAX = 6;
    const FIELD_ID_MTB_SCALE = 0;
    const FIELD_ID_ROUGHNESS = 1;
    const FIELD_ID_JOLT = 2;
    const FIELD_ID_STEER = 3;
    const TICK_MS = 1000;
    const SAMPLE_HZ = 25;
    const SENSOR_STALE_S = 3;   // äldre sensorvärden än så skrivs inte

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
    var _rough = null;       // senaste värden, null = inga data
    var _jolt = null;
    var _steer = null;
    var _sensorAge = 0;      // sekunder sedan senaste paket

    function initialize() { View.initialize(); }

    // ---- Livscykel -------------------------------------------------------

    function onShow() {
        startGps();
        startSensors();
        if (_timer == null) {
            _timer = new Timer.Timer();
            _timer.start(method(:onTick), TICK_MS, true);
        }
    }

    // Stänger av allt. Anropas från AppBase.onStop(). En session som
    // fortfarande finns kvar sparas så att inget spår går förlorat.
    function shutdown() {
        if (_timer != null) { _timer.stop(); _timer = null; }
        finishSession();
        stopSensors();
        stopGps();
    }

    // ---- GPS -------------------------------------------------------------

    // Slår explicit på kontinuerlig positionering. GPS hålls igång under hela
    // appens livstid, alltså både före start, under inspelning och i paus.
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

    // true när det finns en riktig, aktuell fix (inte bara "last known").
    function hasGpsFix() {
        return _gpsQuality >= Position.QUALITY_POOR;
    }

    // ---- Rörelsesensorer --------------------------------------------------

    function startSensors() {
        if (_sensorsOn) { return; }
        // Puls från klockan samt ANT+-kadens/fart om sådana är parkopplade.
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
            // Utan gyroskop: bara skakningar.
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

    // Skriver senaste sensorvärden till developer fields, som writeScale().
    function writeSensors() {
        if (_session == null || !_session.isRecording() || _sensorAge > SENSOR_STALE_S) { return; }
        if (_roughField != null && _rough != null) { _roughField.setData(_rough); }
        if (_joltField != null && _jolt != null) { _joltField.setData(_jolt); }
        if (_steerField != null && _steer != null) { _steerField.setData(_steer); }
    }

    // ---- 1 Hz-tick ---------------------------------------------------------

    function onTick() as Void {
        // Pollar även kvaliteten, ifall positionshändelser uteblir när
        // mottagningen försvinner. Då ska statusen falla tillbaka till WAIT GPS.
        var info = Position.getInfo();
        if (info != null) { setGpsQuality(info.accuracy); }
        writeScale();
        _sensorAge += 1;
        writeSensors();
        if (_session != null && _session.isRecording()) { WatchUi.requestUpdate(); }
    }

    // Skriver det aktuella tillståndet till developer field. Anropas i takt
    // med FIT-records (1 Hz + positionshändelser), inte bara vid knapptryck.
    function writeScale() {
        if (_scaleField != null && _session != null && _session.isRecording()) {
            _scaleField.setData(_scale);
        }
    }

    // ---- Knappåtgärder -----------------------------------------------------

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
            // START: skapa session och developer field, börja spela in.
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
            // PAUS
            _session.stop();
            vibrate(60, 150);
        } else {
            // ÅTERUPPTA: skriv värdet direkt så första record efter paus är rätt.
            _session.start();
            writeScale();
            vibrate(100, 300);
        }
        WatchUi.requestUpdate();
    }

    // STOP: stoppa, spara FIT-aktiviteten och avsluta appen.
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

        // GPS-status: alltid synlig, även under inspelning.
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

        // Under inspelning: levande sensorvärden, så att man ser att de kommer in.
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

// Ren beräkning, fri från sensor-API:t så att den går att enhetstesta.
// ax/ay/az i mG, wx/wy/wz i grader/s (null = inget gyroskop).
// Returnerar [roughness, jolt, steer]; steer är null utan gyroskop.
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
            // vridning kring tyngdkraftens riktning = styrrörelse
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
