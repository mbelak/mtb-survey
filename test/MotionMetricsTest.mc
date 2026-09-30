import Toybox.Lang;
using Toybox.Test;
using Toybox.Math;

// Kör: monkeyc -t ... och sedan monkeydo <prg> epix2 -t

(:test)
function stillaGerNoll(logger as Test.Logger) as Boolean {
    // Klockan stilla, tyngdkraften längs z: inga skakningar, ingen styrning.
    var ax = [0, 0, 0, 0], ay = [0, 0, 0, 0], az = [1000, 1000, 1000, 1000];
    var w0 = [0.0, 0.0, 0.0, 0.0];
    var r = motionMetrics(ax, ay, az, w0, w0, w0);
    logger.debug("stilla " + r);
    return r[0] < 0.01 && r[1] < 0.01 && r[2] < 0.01;
}

(:test)
function skakningarRmsOchTopp(logger as Test.Logger) as Boolean {
    // |a| växlar 900/1100 mG: RMS 100 och största avvikelse 100.
    var ax = [0, 0, 0, 0], ay = [0, 0, 0, 0], az = [900, 1100, 900, 1100];
    var r = motionMetrics(ax, ay, az, null, null, null);
    logger.debug("skak " + r);
    return (r[0] - 100.0).abs() < 0.5 && (r[1] - 100.0).abs() < 0.5 && r[2] == null;
}

(:test)
function styrningKringLodaxelnOberoendeAvLutning(logger as Test.Logger) as Boolean {
    // Klockan lutad 90 grader (tyngdkraft längs x). Vridning kring x växlar ±20 grader/s
    // och ska ge steer 20. Vridning kring y (vinkelrät mot lodlinjen) ska ignoreras.
    var ax = [1000, 1000, 1000, 1000], ay = [0, 0, 0, 0], az = [0, 0, 0, 0];
    var wx = [20.0, -20.0, 20.0, -20.0], wy = [50.0, -50.0, 50.0, -50.0], wz = [0.0, 0.0, 0.0, 0.0];
    var r = motionMetrics(ax, ay, az, wx, wy, wz);
    logger.debug("styr " + r);
    return (r[2] - 20.0).abs() < 0.5;
}

(:test)
function jamnKurvaGerIngenStyrkorrigering(logger as Test.Logger) as Boolean {
    // Konstant 30 grader/s kring lodaxeln = en jämn kurva, inte korrigeringar.
    var ax = [0, 0, 0, 0], ay = [0, 0, 0, 0], az = [1000, 1000, 1000, 1000];
    var wz = [30.0, 30.0, 30.0, 30.0], w0 = [0.0, 0.0, 0.0, 0.0];
    var r = motionMetrics(ax, ay, az, w0, w0, wz);
    logger.debug("kurva " + r);
    return r[2] < 0.01;
}
